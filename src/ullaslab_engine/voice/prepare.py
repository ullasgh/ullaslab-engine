"""Reference-recording QA, preprocessing and reference-clip selection.

Everything here runs on local files only. Nothing is uploaded or printed beyond scalar metrics: the
recording is biometric data (see docs/voice.md)."""
from __future__ import annotations
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt, stft, istft
from ..audio import Wav, loudness_lufs, normalize_loudness, resample, true_peak_dbtp
from .naturalness import FRAME_S, HOP_S, _frames, f0_track

# QA thresholds (documented in docs/voice.md)
SNR_OK_DB, SNR_REDO_DB = 30.0, 20.0
CLIP_OK_PCT, CLIP_REDO_PCT = 0.01, 0.1
RT_WARN_S, RT_REDO_S = 0.4, 0.7
NOISE_WARN_DBFS = -50.0


def decode(src: Path, dst: Path, sr: int = 48000) -> Path:
    """Any container -> mono PCM16 WAV using ffmpeg, else macOS afconvert."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)]
    elif shutil.which("afconvert"):
        cmd = ["afconvert", "-f", "WAVE", "-d", f"LEI16@{sr}", "-c", "1", str(src), str(dst)]
    else:
        raise RuntimeError("need ffmpeg or afconvert to decode non-WAV input")
    subprocess.run(cmd, check=True)
    return dst


def load_any(path: Path, work: Path) -> Wav:
    path = Path(path)
    if path.suffix.lower() in (".wav", ".flac", ".ogg"):
        return Wav.load(path)
    return Wav.load(decode(path, work / "decoded.wav"))


def _frame_db(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    n, hop = int(FRAME_S * sr), int(HOP_S * sr)
    fr = _frames(x, n, hop)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    return fr, 20 * np.log10(np.maximum(rms, 1e-9))


@dataclass
class QAReport:
    metrics: dict
    verdict: str                      # OK | OK_WITH_NOTES | RE_RECORD
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def reverb_hint_s(db: np.ndarray) -> float:
    """Median time (s) for the level to fall 15 dB after a speech offset (a decay-slope proxy for RT60/4).
    Dry close-mic speech falls in well under 0.1 s; a reverberant room takes several hundred ms."""
    hi = np.percentile(db, 90)
    times = []
    i = 0
    while i < len(db) - 2:
        if db[i] > hi - 12 and db[i + 1] < db[i] - 6:  # offset
            j = i + 1
            while j < len(db) and db[j] > db[i] - 15 and j - i < 60:
                j += 1
            if j < len(db) and db[j] <= db[i] - 15:
                times.append((j - i) * HOP_S)
            i = j
        else:
            i += 1
    return float(np.median(times)) if len(times) >= 3 else float("nan")


def analyze(w: Wav, source_sr: int | None = None) -> QAReport:
    x = w.samples.astype(np.float64)
    _, db = _frame_db(x, w.sr)
    noise = float(np.percentile(db, 10))
    speech = float(np.percentile(db, 90))
    snr = speech - noise
    hum = _hum_db(x, w.sr)
    m = {
        "duration_s": round(len(x) / w.sr, 1),
        "source_sample_rate": source_sr or w.sr,
        "clipping_pct": round(float((np.abs(x) >= 0.999).mean() * 100), 4),
        "noise_floor_dbfs": round(noise, 1),
        "speech_level_dbfs": round(speech, 1),
        "snr_db": round(snr, 1),
        "reverb_hint_s": round(reverb_hint_s(db), 3),
        "hum_db_over_floor": round(hum, 1),
        "loudness_lufs": round(loudness_lufs(w), 1),
        "true_peak_dbtp": round(true_peak_dbtp(w), 1),
        "dc_offset": round(float(abs(x.mean())), 5),
    }
    redo, notes = [], []
    if m["duration_s"] < 60:
        notes.append("under 1 minute: fine for a 3-clip reference, too short for fine-tuning")
    if m["source_sample_rate"] < 22050:
        redo.append(f"sample rate {m['source_sample_rate']} Hz is below 22.05 kHz")
    if snr < SNR_REDO_DB:
        redo.append(f"SNR {snr:.0f} dB is below {SNR_REDO_DB:.0f} dB: noisy room or mic too far")
    elif snr < SNR_OK_DB:
        notes.append(f"SNR {snr:.0f} dB: usable after light denoise")
    if m["clipping_pct"] > CLIP_REDO_PCT:
        redo.append(f"clipping {m['clipping_pct']}% of samples: lower the input gain")
    elif m["clipping_pct"] > CLIP_OK_PCT:
        notes.append("a few clipped samples")
    rt = m["reverb_hint_s"]
    if rt == rt:
        if rt > RT_REDO_S:
            redo.append(f"reverb hint {rt:.2f}s: too much room echo")
        elif rt > RT_WARN_S:
            notes.append(f"reverb hint {rt:.2f}s: slight room sound")
    if noise > NOISE_WARN_DBFS:
        notes.append(f"noise floor {noise:.0f} dBFS is high")
    if hum > 15:
        notes.append("mains hum (50/60 Hz) detected; the high-pass removes most of it")
    verdict = "RE_RECORD" if redo else ("OK_WITH_NOTES" if notes else "OK")
    return QAReport(m, verdict, redo, notes)


def _hum_db(x: np.ndarray, sr: int) -> float:
    n = min(len(x), sr * 30)
    spec = np.abs(np.fft.rfft(x[:n] * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    def band(c, bw=1.5): return spec[(f > c - bw) & (f < c + bw)].max(initial=1e-18)
    base = np.median(spec[(f > 40) & (f < 200)]) + 1e-18
    return float(10 * np.log10(max(band(50), band(60)) / base))


# ---------- preprocessing ----------

def denoise(w: Wav, strength_db: float = 12.0) -> Wav:
    """Light stationary spectral gate (own implementation, numpy/scipy only): noise profile from the quietest
    15% of frames, soft mask floored at -strength_db so speech keeps its natural texture."""
    x = w.samples.astype(np.float64)
    nper = 1024 if w.sr <= 24000 else 2048
    _, _, Z = stft(x, w.sr, nperseg=nper, noverlap=nper * 3 // 4)
    mag = np.abs(Z)
    energy = mag.sum(axis=0)
    quiet = energy <= np.percentile(energy, 15)
    prof = np.sqrt((mag[:, quiet] ** 2).mean(axis=1, keepdims=True)) + 1e-12
    snr = mag / (prof * 1.5)
    mask = np.clip(1 - 1 / np.maximum(snr, 1e-6) ** 2, 0, 1)
    mask = np.maximum(mask, 10 ** (-strength_db / 20))
    from scipy.ndimage import uniform_filter
    mask = uniform_filter(mask, size=(3, 3))
    _, y = istft(Z * mask, w.sr, nperseg=nper, noverlap=nper * 3 // 4)
    y = y[: len(x)]
    y = sosfiltfilt(butter(2, 70, "high", fs=w.sr, output="sos"), y)
    return Wav(y.astype(np.float32), w.sr)


def tighten_pauses(w: Wav, max_pause_s: float = 0.6, edge_s: float = 0.15, margin_db: float = 40.0) -> Wav:
    """Trim leading/trailing silence and shorten internal silences to max_pause_s."""
    x = w.samples
    n, hop = int(FRAME_S * w.sr), int(HOP_S * w.sr)
    _, db = _frame_db(x.astype(np.float64), w.sr)
    ref = np.percentile(db, 95)
    voiced = db > ref - margin_db
    if not voiced.any():
        return w
    first, last = np.argmax(voiced), len(voiced) - np.argmax(voiced[::-1])
    out, i = [], first
    while i < last:
        if voiced[i]:
            j = i
            while j < last and voiced[j]: j += 1
            out.append(x[i * hop: min(len(x), j * hop + n)])
            i = j
        else:
            j = i
            while j < last and not voiced[j]: j += 1
            gap = min((j - i) * hop, int(max_pause_s * w.sr))
            out.append(np.zeros(gap, dtype=np.float32))
            i = j
    pad = np.zeros(int(edge_s * w.sr), dtype=np.float32)
    return Wav(np.concatenate([pad, *out, pad]).astype(np.float32), w.sr)


def preprocess(w: Wav, sr: int = 24000) -> Wav:
    """mono -> denoise -> tighten pauses -> resample to sr -> loudness-normalise (-23 LUFS for references,
    comfortable and well below clipping; the final narration is normalised separately)."""
    w = denoise(w)
    w = tighten_pauses(w)
    w = resample(w, sr)
    return normalize_loudness(w, target=-23.0)


# ---------- clip selection ----------

# score = 100 * weighted sum of the components below, each in [0, 1]
WEIGHTS = {"clean": 0.30, "steady_pitch": 0.25, "prosody": 0.20, "no_artifacts": 0.15, "voiced": 0.10}


def _score_window(x: np.ndarray, sr: int) -> dict:
    fr, db = _frame_db(x.astype(np.float64), sr)
    ref = np.percentile(db, 95)
    snr = ref - np.percentile(db, 10)
    f0 = f0_track(x.astype(np.float64), sr, rms_floor=10 ** ((ref - 35) / 20))
    v = f0[~np.isnan(f0)]
    if len(v) < 20:
        return {"total": 0.0}
    st = 12 * np.log2(v / np.median(v))
    # steady pitch: small octave-error rate and small slow drift (30-frame moving median)
    jumps = np.mean(np.abs(np.diff(st)) > 6)
    k = 30
    drift = np.std(np.convolve(st, np.ones(k) / k, "valid")) if len(st) > k else np.std(st)
    steady = float(np.clip(1 - 4 * jumps, 0, 1) * np.clip(1 - max(0, drift - 1.0) / 3.0, 0, 1))
    # prosody: pitch std 2-5 semitones is lively but calm; monotone or theatrical is penalised
    s = float(np.std(st))
    prosody = float(np.clip(1 - (2 - s) / 2, 0, 1) if s < 2 else np.clip(1 - (s - 5) / 4, 0, 1))
    # artifacts: clicks (sample-difference outliers) and breaths (flat-spectrum low-level bursts)
    d = np.abs(np.diff(x))
    clicks = float(np.mean(d > 12 * (np.median(d) + 1e-9)) > 0.002)
    sp = np.abs(np.fft.rfft(fr * np.hanning(fr.shape[1]), axis=1)) ** 2 + 1e-12
    flat = np.exp(np.log(sp).mean(axis=1)) / sp.mean(axis=1)
    mid = (db < ref - 18) & (db > ref - 38)
    breaths = float(np.mean(mid & (flat > 0.12)))
    clean_art = float(np.clip(1 - 8 * breaths - 0.5 * clicks, 0, 1))
    voiced = len(v) / len(f0)
    voiced_s = float(np.clip(1 - abs(voiced - 0.65) / 0.35, 0, 1))
    clean = float(np.clip((snr - 20) / 25, 0, 1))
    comp = {"clean": clean, "steady_pitch": steady, "prosody": prosody, "no_artifacts": clean_art, "voiced": voiced_s}
    comp["total"] = float(100 * sum(WEIGHTS[k] * comp[k] for k in WEIGHTS))
    return comp


def select_clips(w: Wav, n: int = 3, lo: float = 10.0, hi: float = 15.0) -> list[dict]:
    """Slide lo..hi second windows that start and end on pauses, score them (WEIGHTS), take the top n
    non-overlapping. Returns [{start, end, total, clean, ...}] best first (metadata only)."""
    x, sr = w.samples, w.sr
    _, db = _frame_db(x.astype(np.float64), sr)
    ref = np.percentile(db, 95)
    pause = db < ref - 30
    # pause boundaries: frame indices inside runs of >= 0.2 s of silence (cut at the middle)
    cuts, run_start = [], None
    for i, p in enumerate(pause):
        if p and run_start is None: run_start = i
        if (not p or i == len(pause) - 1) and run_start is not None:
            if (i - run_start) * HOP_S >= 0.2: cuts.append((run_start + i) // 2)
            run_start = None
    cands = []
    for a in cuts:
        for b in cuts:
            d = (b - a) * HOP_S
            if lo <= d <= hi:
                s = _score_window(x[a * int(HOP_S * sr): b * int(HOP_S * sr)], sr)
                cands.append({"start": round(a * HOP_S, 2), "end": round(b * HOP_S, 2),
                              **{k: round(v, 3) for k, v in s.items()}})
    cands.sort(key=lambda c: -c["total"])
    chosen = []
    for c in cands:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in chosen):
            chosen.append(c)
        if len(chosen) == n:
            break
    return chosen


def write_clips(w: Wav, clips: list[dict], outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, c in enumerate(clips, 1):
        seg = w.samples[int(c["start"] * w.sr): int(c["end"] * w.sr)]
        p = outdir / f"clip{i}.wav"
        sf.write(str(p), seg, w.sr, subtype="PCM_16")
        paths.append(p)
    return paths
