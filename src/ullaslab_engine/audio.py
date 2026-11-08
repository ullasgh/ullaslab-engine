"""Audio helpers: Wav container, loudness normalisation (-14 LUFS), true peak, timeline assembly."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import resample_poly

TARGET_LUFS = -14.0
TRUE_PEAK_CEILING_DBTP = -1.0


@dataclass
class Wav:
    samples: np.ndarray  # float32 mono, shape (n,)
    sr: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sr

    def save(self, path: Path) -> Path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), self.samples, self.sr, subtype="PCM_16")
        return Path(path)

    @staticmethod
    def load(path: Path) -> "Wav":
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return Wav(data.mean(axis=1).astype(np.float32), sr)


def resample(w: Wav, sr: int) -> Wav:
    if w.sr == sr:
        return w
    from math import gcd
    g = gcd(w.sr, sr)
    return Wav(resample_poly(w.samples, sr // g, w.sr // g).astype(np.float32), sr)


def true_peak_dbtp(w: Wav) -> float:
    """4x oversampled peak (ITU-R BS.1770 style estimate)."""
    if len(w.samples) == 0:
        return -120.0
    up = resample_poly(w.samples, 4, 1)
    peak = float(np.max(np.abs(up)))
    return 20 * np.log10(max(peak, 1e-9))


def loudness_lufs(w: Wav) -> float:
    if w.duration < 0.5:
        return -70.0
    meter = pyln.Meter(w.sr)
    return float(meter.integrated_loudness(w.samples.astype(np.float64)))


def _limit(x: np.ndarray, sr: int, ceiling_db: float) -> np.ndarray:
    """Look-ahead peak limiter: smooth gain envelope so |x| stays below the ceiling."""
    ceiling = 10 ** (ceiling_db / 20)
    mag = np.abs(x)
    gain = np.minimum(1.0, ceiling / np.maximum(mag, 1e-9))
    win = max(1, int(sr * 0.005))
    gain = minimum_filter1d(gain, size=2 * win + 1, mode="nearest")
    gain = uniform_filter1d(gain, size=2 * win + 1, mode="nearest")
    return (x * gain).astype(np.float32)


def normalize_loudness(w: Wav, target: float = TARGET_LUFS, ceiling: float = TRUE_PEAK_CEILING_DBTP) -> Wav:
    """Gain to target LUFS, then limit to the true-peak ceiling; iterate so both hold."""
    x = w.samples.astype(np.float64)
    if len(x) == 0 or float(np.max(np.abs(x))) < 1e-6:
        return w
    cur = Wav(x.astype(np.float32), w.sr)
    for _ in range(10):
        lufs = loudness_lufs(cur)
        gain = 10 ** ((target - lufs) / 20)
        cur = Wav((cur.samples * gain).astype(np.float32), w.sr)
        cur = Wav(_limit(cur.samples, w.sr, ceiling - 0.6), w.sr)  # 0.6 dB margin for inter-sample peaks
        if abs(loudness_lufs(cur) - target) <= 0.3 and true_peak_dbtp(cur) <= ceiling - 0.2:
            break
    over = true_peak_dbtp(cur) - (ceiling - 0.2)  # final safety: 0.2 dB margin for lossy encoding
    if over > 0:
        cur = Wav((cur.samples * 10 ** (-over / 20)).astype(np.float32), w.sr)
    return cur


def trim_silence(w: Wav, thresh_db: float = -50.0, keep_s: float = 0.08) -> Wav:
    thresh = 10 ** (thresh_db / 20)
    idx = np.where(np.abs(w.samples) > thresh)[0]
    if len(idx) == 0:
        return w
    k = int(keep_s * w.sr)
    return Wav(w.samples[max(0, idx[0] - k): idx[-1] + k], w.sr)


def assemble(segments: list[tuple[float, Wav]], sr: int, total_s: float | None = None) -> Wav:
    """Place (start_seconds, wav) clips on a silent timeline (later clips overwrite only silence by summing)."""
    end = max((s + w.duration for s, w in segments), default=0.0)
    n = int(round(max(end, total_s or 0.0) * sr))
    out = np.zeros(n, dtype=np.float32)
    for start, w in segments:
        w = resample(w, sr)
        i = int(round(start * sr))
        out[i:i + len(w.samples)] += w.samples[: max(0, n - i)]
    return Wav(out, sr)


def max_silence_s(w: Wav, thresh_db: float = -45.0, frame_s: float = 0.02) -> float:
    frame = max(1, int(w.sr * frame_s))
    n = len(w.samples) // frame
    if n == 0:
        return 0.0
    rms = np.sqrt(np.mean(w.samples[: n * frame].reshape(n, frame) ** 2, axis=1))
    silent = rms < 10 ** (thresh_db / 20)
    best = run = 0
    for s in silent:
        run = run + 1 if s else 0
        best = max(best, run)
    return best * frame_s
