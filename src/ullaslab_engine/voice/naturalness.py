"""Naturalness gate: MOS-style 0-100 score from objective proxies, thresholds in config/quality.yaml
(A3b_naturalness). No learned MOS model is used: UTMOS/SQUIM/DNSMOS weights have no clearly
commercial-OK licence (checked 2026-11), so the proxies below are the gate. A learned predictor can be
plugged in with `extra_scorer` without changing callers."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
from ..audio import Wav, resample
from ..config import quality

FRAME_S = 0.040
HOP_S = 0.020


def _frames(x: np.ndarray, n: int, hop: int) -> np.ndarray:
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    idx = np.arange(0, len(x) - n + 1, hop)[:, None] + np.arange(n)[None, :]
    return x[idx]


def f0_track(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0, thr: float = 0.5,
             rms_floor: float = 0.01) -> np.ndarray:
    """Autocorrelation pitch per frame (Hz, nan when unvoiced). Good enough for variance statistics."""
    n, hop = int(FRAME_S * sr), int(HOP_S * sr)
    fr = _frames(x, n, hop)
    fr = fr - fr.mean(axis=1, keepdims=True)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    lo, hi = int(sr / fmax), int(sr / fmin)
    nfft = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(fr * np.hanning(n), nfft)
    ac = np.fft.irfft(np.abs(spec) ** 2)[:, : hi + 1]
    ac = ac / np.maximum(ac[:, :1], 1e-12)
    seg = ac[:, lo: hi + 1]
    k = seg.argmax(axis=1)
    peak = seg[np.arange(len(seg)), k]
    f0 = sr / (k + lo)
    f0[(peak < thr) | (rms < rms_floor)] = np.nan
    return f0


@dataclass
class NaturalnessReport:
    score: float
    metrics: dict
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def metrics(w: Wav) -> dict:
    w = resample(w, 16000)
    x = w.samples.astype(np.float64)
    n, hop = int(FRAME_S * w.sr), int(HOP_S * w.sr)
    fr = _frames(x, n, hop)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    peak_db = np.percentile(db, 95)
    speech = db > peak_db - 30  # relative gate: robust to level and room tone
    f0 = f0_track(x, w.sr, rms_floor=10 ** ((peak_db - 35) / 20))
    voiced = f0[~np.isnan(f0)]
    st = 12 * np.log2(voiced / np.median(voiced)) if len(voiced) > 5 else np.array([0.0])
    st = st[np.abs(st) <= 8]  # drop octave errors / edge frames
    if len(st) < 3:
        st = np.array([0.0])
    # pauses: runs of non-speech frames
    runs, run = [], 0
    for s in speech:
        if not s:
            run += 1
        else:
            if run: runs.append(run * HOP_S)
            run = 0
    inner = [r for r in runs if r >= 0.15]
    # spectral flatness over speech frames
    sp = np.abs(np.fft.rfft(fr[speech] * np.hanning(n), axis=1)) ** 2 + 1e-12 if speech.any() else np.ones((1, 2))
    flat = float(np.mean(np.exp(np.log(sp).mean(axis=1)) / sp.mean(axis=1)))
    # syllable-rate proxy: peaks of the smoothed envelope
    env = np.convolve(rms, np.ones(3) / 3, "same")
    thr = 10 ** ((peak_db - 18) / 20)
    pk = np.sum((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr))
    dur = len(x) / w.sr
    return {
        "duration_s": round(dur, 2),
        "pitch_std_st": round(float(np.std(st)), 2),
        "voiced_ratio": round(float(len(voiced) / max(1, len(f0))), 3),
        "pause_ratio": round(float((~speech).mean()), 3),
        "pause_max_s": round(max(runs, default=0.0), 2),
        "pause_count_per_10s": round(len(inner) / max(dur, 0.1) * 10, 2),
        "syllable_rate": round(float(pk / max(dur, 0.1)), 2),
        "spectral_flatness": round(flat, 4),
        "clipping_pct": round(float((np.abs(x) > 0.999).mean() * 100), 4),
    }


# metric -> (low, high) keys in quality.yaml
_BOUNDS = {
    "pitch_std_st": ("pitch_std_min_st", "pitch_std_max_st"),
    "voiced_ratio": ("voiced_ratio_min", None),
    "pause_ratio": (None, "pause_ratio_max"),
    "pause_max_s": (None, "pause_max_s"),
    "syllable_rate": ("syllable_rate_min", "syllable_rate_max"),
    "spectral_flatness": (None, "spectral_flatness_max"),
    "clipping_pct": (None, "clipping_pct_max"),
}


def score(w: Wav, cfg: dict | None = None, extra_scorer: Callable[[Wav], float] | None = None) -> NaturalnessReport:
    cfg = cfg or quality()["A3b_naturalness"]
    m = metrics(w)
    fails, ok = [], 0
    for key, (lo, hi) in _BOUNDS.items():
        v = m[key]
        bad = (lo and v < cfg[lo]) or (hi and v > cfg[hi])
        if bad:
            fails.append(f"{key}={v} outside [{cfg.get(lo, '-')}, {cfg.get(hi, '-')}]")
        else:
            ok += 1
    sc = 100.0 * ok / len(_BOUNDS)
    if extra_scorer:
        sc = 0.5 * sc + 0.5 * float(extra_scorer(w))
    if sc < cfg["min_score"]:
        fails.append(f"score={sc:.0f} < {cfg['min_score']}")
    return NaturalnessReport(round(sc, 1), m, fails)
