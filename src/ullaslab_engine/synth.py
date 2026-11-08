"""Per-segment synthesis and timeline construction.

Natural timeline: segments back to back (used for the master and for the Hindi visual variant).
Slot timeline: dub segments placed at the master's segment starts so the track lines up with the
English master; overruns are recorded (translator must shorten) and fail the duration gate.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from .audio import Wav, assemble, trim_silence
from .bundle import seg_text
from .config import quality
from .voice.narrate import narrate as default_tts

SR = 48000
GAP_S = 0.3
TAIL_S = 0.5
DISCLAIMER_S = 3.0


def synth_segments(m: dict, lang: str, ref_wav: Path | None,
                   tts_fn: Callable[..., Wav] = default_tts) -> list[Wav]:
    """One engine per track: the first segment picks it (primary, else fallback); later segments must
    use the same engine, so a transient failure cannot splice a stock voice into a cloned track."""
    out, pin = [], None
    for s in m["segments"]:
        kw = {"engine": pin} if pin else {}
        w = tts_fn(seg_text(m, s, lang), lang, ref_wav, normalize=False, **kw)
        pin = pin or getattr(w, "engine", None)
        out.append(trim_silence(w))
    return out


def beats_for(start: float, end: float) -> list[float]:
    """Visual change points inside [start, end): at most 85% of max_seconds_between_changes apart."""
    step = quality()["A4_visual_pacing"]["max_seconds_between_changes"] * 0.85
    out, t = [], start
    while t < end - 0.05:
        out.append(round(t, 3))
        t += step
    return out


def _scene_windows(m: dict, seg_times: dict[str, tuple[float, float]]) -> tuple[list[dict], float]:
    scenes = [dict(s) for s in m["scenes"]]
    if not scenes or scenes[-1]["kind"] != "disclaimer":
        scenes.append({"id": "disclaimer", "kind": "disclaimer", "segments": []})
    narr_end = max(e for _, e in seg_times.values())
    out = []
    for i, sc in enumerate(scenes):
        if sc["kind"] == "disclaimer" and not sc.get("segments"):
            continue
        ids = sc.get("segments", [])
        if not ids:
            raise ValueError(f"scene {sc['id']} has no segments")
        start = 0.0 if not out else min(seg_times[j][0] for j in ids)
        out.append({"id": sc["id"], "kind": sc["kind"], "start": start})
    for i, o in enumerate(out):
        o["end"] = out[i + 1]["start"] if i + 1 < len(out) else narr_end + TAIL_S
    total = out[-1]["end"]
    if not any(s["kind"] == "disclaimer" for s in out):
        out.append({"id": "disclaimer", "kind": "disclaimer", "start": total, "end": total + DISCLAIMER_S})
        total += DISCLAIMER_S
    for o in out:
        o["start"], o["end"] = round(o["start"], 3), round(o["end"], 3)
        o["beats"] = beats_for(o["start"], o["end"])
    return out, round(total, 3)


def natural_timeline(m: dict, lang: str, wavs: list[Wav]) -> tuple[Wav, dict]:
    cur, placed, times = 0.0, [], {}
    for s, w in zip(m["segments"], wavs):
        placed.append((cur, w))
        times[s["id"]] = (cur, cur + w.duration)
        cur += w.duration + GAP_S
    scenes, total = _scene_windows(m, times)
    audio = assemble(placed, SR, total)
    tl = {"lang": lang, "mode": "natural", "total_s": total, "sr": SR,
          "segments": [{"id": k, "start": round(a, 3), "end": round(b, 3)} for k, (a, b) in times.items()],
          "scenes": scenes, "overruns": []}
    return audio, tl


def slot_timeline(m: dict, lang: str, wavs: list[Wav], master_tl: dict) -> tuple[Wav, dict]:
    slots = {s["id"]: (s["start"], s["end"]) for s in master_tl["segments"]}
    order = [s["id"] for s in m["segments"]]
    placed, times, overruns = [], {}, []
    for i, (sid, w) in enumerate(zip(order, wavs)):
        a, b = slots[sid]
        nxt = slots[order[i + 1]][0] if i + 1 < len(order) else master_tl["total_s"]
        if w.duration > (nxt - a) - 0.05:  # would collide with the next segment or run past the end
            overruns.append(sid)
        placed.append((a, w))
        times[sid] = (a, a + w.duration)
    audio = assemble(placed, SR, master_tl["total_s"])
    tl = {"lang": lang, "mode": "slot", "total_s": master_tl["total_s"], "sr": SR,
          "segments": [{"id": k, "start": round(a, 3), "end": round(b, 3)} for k, (a, b) in times.items()],
          "scenes": master_tl["scenes"], "overruns": overruns}
    return audio, tl
