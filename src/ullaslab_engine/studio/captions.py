"""Caption cues with per-word timing (burned in by Remotion with word highlight) and SRT export."""
from __future__ import annotations
from ..captions import limits, to_srt

MAX_CUE_S = 3.6
HOLD_S = 0.35
_END = (".", "?", "!", "…", "。")


def build_cues(scenes: list[dict], lang: str = "en") -> list[dict]:
    """cue = {start, end, lines: [[{w,start,end}, ...], ...]}. <= max_lines lines of <= per_line chars, never
    crossing a sentence end or exceeding MAX_CUE_S; rhythm follows the spoken words."""
    per_line, max_lines = limits(lang)
    words = [w for sc in scenes for w in (sc["narration"].get("words") or [])]
    cues, lines, line, size = [], [], [], 0

    def flush():
        nonlocal lines, line, size
        if line:
            lines.append(line)
        if lines:
            cues.append({"start": lines[0][0]["start"], "end": lines[-1][-1]["end"], "lines": lines})
        lines, line, size = [], [], 0

    for w in words:
        add = len(w["w"]) + (1 if line else 0)
        if line and size + add > per_line:
            lines.append(line)
            line, size = [], 0
            add = len(w["w"])
            if len(lines) >= max_lines:
                flush()
        cur_start = (lines[0][0]["start"] if lines else line[0]["start"]) if (lines or line) else w["start"]
        if (lines or line) and w["end"] - cur_start > MAX_CUE_S:
            flush()
            add = len(w["w"])
        line.append(w)
        size += add
        if w["w"].endswith(_END):
            flush()
    flush()
    for i, c in enumerate(cues):   # hold briefly, never overlap the next cue
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + HOLD_S
        c["end"] = round(max(min(c["end"] + HOLD_S, nxt), c["start"] + 0.2), 3)
        c["start"] = round(c["start"], 3)
    return cues


def cues_to_srt(cues: list[dict]) -> str:
    return to_srt([{"start": c["start"], "end": c["end"], "lines": [" ".join(w["w"] for w in ln) for ln in c["lines"]]} for c in cues])
