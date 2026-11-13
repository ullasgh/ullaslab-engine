"""Best-of-N takes per line (owner decision 2026-11-13: "sample 4").

Each narrated line is synthesised N times with deterministic seeds (base + TAKE_SEED_STEP * j). Every take is checked for accuracy
with the same ASR and WER canonicalisation as the voice gate (asr.error_rate), measured for pitch range, and the widest-pitch take
among the ELIGIBLE ones is kept. Eligible = the take(s) with the line's lowest WER, a length within 0.8-1.25 x the median of the
line's takes (no truncated or run-on take) and no pitch-jump artefacts (the share of voiced frame-to-frame jumps over 4 semitones
stays under max(0.06, 2 x the median share of all takes)). If nothing is eligible the lowest-WER take is used. Selection only
chooses between candidate takes of the same line; it changes no gate, limit or threshold (the file-level gates and the WER-only
retry run unchanged afterwards).

Pitch measure: pYIN on the take (librosa, 16 kHz, 65-400 Hz) in semitones re 100 Hz; frames more than 8 st from the take's
median are dropped as octave-jump artefacts; the measure is the 10th to 90th percentile spread of what is left."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TAKE_SEED_STEP = 10        # take j of a line uses seed base + 10 j: clear of chunk retries (+100 k), the naturalness retry (+1)
MAX_TAKES = 8              # and the WER-only attempts (+1000 i)
ARTEFACT_FLOOR = 0.06
ARTEFACT_FACTOR = 2.0
DUR_LOW, DUR_HIGH = 0.8, 1.25
OUTLIER_ST = 8.0           # frames further than this from the take's median pitch are octave-jump artefacts
JUMP_ST = 4.0


@dataclass
class Take:
    seed: int
    wer: float             # percent, canonical WER of this take against its line text
    dur: float             # seconds, edges trimmed
    pitch: float           # p10-p90 pitch spread in semitones
    art: float             # share of pitch jumps > JUMP_ST
    wave: object = None    # the synthesised Wav (not serialised)


def pitch_metrics(x: np.ndarray, sr: int) -> tuple[float, float]:
    """(p10-p90 pitch spread in semitones, artefact share) of one take. (0.0, 0.0) when almost nothing is voiced."""
    import librosa
    y = x.astype(np.float32)
    if sr != 16000:
        y = librosa.resample(y, orig_sr=sr, target_sr=16000)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=400, sr=16000, frame_length=1024, hop_length=160)
    ok = voiced & ~np.isnan(f0)
    st = 12 * np.log2(f0[ok] / 100.0)
    return pitch_from_semitones(st)


def pitch_from_semitones(st: np.ndarray) -> tuple[float, float]:
    if len(st) < 6:
        return 0.0, 0.0
    kept = st[np.abs(st - np.median(st)) <= OUTLIER_ST]
    if len(kept) < 6:
        return 0.0, 0.0
    jumps = np.abs(np.diff(st))
    art = float((jumps > JUMP_ST).mean()) if len(jumps) else 0.0
    return float(np.percentile(kept, 90) - np.percentile(kept, 10)), art


def artefact_limit(all_takes: list[Take]) -> float:
    arts = [t.art for t in all_takes]
    return max(ARTEFACT_FLOOR, ARTEFACT_FACTOR * float(np.median(arts))) if arts else ARTEFACT_FLOOR


def select_take(takes: list[Take], art_limit: float) -> int:
    """Index of the kept take of one line (see the module docstring). Ties go to the earliest take."""
    if len(takes) == 1:
        return 0
    med_dur = float(np.median([t.dur for t in takes]))
    best_wer = min(t.wer for t in takes)
    ok = [i for i, t in enumerate(takes)
          if t.wer <= best_wer and DUR_LOW * med_dur <= t.dur <= DUR_HIGH * med_dur and t.art <= art_limit]
    if not ok:
        return min(range(len(takes)), key=lambda i: takes[i].wer)
    return max(ok, key=lambda i: (takes[i].pitch, -i))


def select_all(lines: list[list[Take]]) -> list[int]:
    lim = artefact_limit([t for ts in lines for t in ts])
    return [select_take(ts, lim) for ts in lines]
