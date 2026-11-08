"""Light post-processing: 70 Hz high-pass, gentle presence lift, de-esser, consistent room tone.
No reverb, compression-heavy or pitch effects: the voice stays the voice."""
from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt, lfilter
from ..audio import Wav

ROOM_TONE_DBFS = -63.0
DESS_BAND = (5000.0, 9000.0)
DESS_THRESH_DB = -3.0   # band-vs-body ratio above which gain is pulled down
DESS_MAX_REDUCTION_DB = 6.0


def highpass(x: np.ndarray, sr: int, fc: float = 70.0) -> np.ndarray:
    return sosfiltfilt(butter(2, fc, "high", fs=sr, output="sos"), x)


def presence(x: np.ndarray, sr: int, f0: float = 3000.0, gain_db: float = 1.2, q: float = 0.8) -> np.ndarray:
    """RBJ peaking biquad."""
    a = 10 ** (gain_db / 40); w0 = 2 * np.pi * f0 / sr; al = np.sin(w0) / (2 * q)
    b = [1 + al * a, -2 * np.cos(w0), 1 - al * a]
    den = [1 + al / a, -2 * np.cos(w0), 1 - al / a]
    return lfilter(np.array(b) / den[0], np.array(den) / den[0], x)


def deess(x: np.ndarray, sr: int) -> np.ndarray:
    if sr < 2 * DESS_BAND[1] * 0.9:
        return x
    sos = butter(4, DESS_BAND, "band", fs=sr, output="sos")
    band = sosfilt(sos, x)
    win = max(1, int(0.005 * sr))
    k = np.ones(win) / win
    env_b = np.sqrt(np.convolve(band ** 2, k, "same") + 1e-12)
    env_x = np.sqrt(np.convolve(x ** 2, k, "same") + 1e-12)
    ratio_db = 20 * np.log10(env_b / env_x)
    red = np.clip(ratio_db - DESS_THRESH_DB, 0, DESS_MAX_REDUCTION_DB)
    gain = 10 ** (-red / 20)
    gain = np.convolve(gain, np.ones(win) / win, "same")
    # reduce only the sibilant band: x - band*(1-gain)
    return x - band * (1 - gain)


def room_tone(n: int, sr: int, level_dbfs: float = ROOM_TONE_DBFS, seed: int = 7) -> np.ndarray:
    """Deterministic low-passed noise at a fixed level so every clip shares the same floor."""
    rng = np.random.default_rng(seed)
    x = sosfilt(butter(2, 2500, "low", fs=sr, output="sos"), rng.standard_normal(n))
    x = highpass(x, sr, 40.0)
    rms = np.sqrt(np.mean(x ** 2)) + 1e-12
    return x / rms * 10 ** (level_dbfs / 20)


def postprocess(w: Wav, room: bool = True) -> Wav:
    x = w.samples.astype(np.float64)
    if len(x) < 64:
        return w
    x = highpass(x, w.sr)
    x = presence(x, w.sr)
    x = deess(x, w.sr)
    if room:
        x = x + room_tone(len(x), w.sr)
    peak = np.max(np.abs(x))
    if peak > 0.98:
        x = x * 0.98 / peak
    return Wav(x.astype(np.float32), w.sr, w.engine)
