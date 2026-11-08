"""Captions: script words timed by ASR alignment (English master) or proportional segment mapping
(translations, no ASR needed). SRT and VTT output. Layout limits come from quality.yaml (A5)."""
from __future__ import annotations
import difflib
from .bundle import normalise_for_wer, seg_text
from .config import quality

NO_SPACE_LANGS = {"ja"}


def tokenise(text: str, lang: str) -> list[str]:
    if lang in NO_SPACE_LANGS:
        return [c for c in text if not c.isspace()]
    return text.split()


def joiner(lang: str) -> str:
    return "" if lang in NO_SPACE_LANGS else " "


def limits(lang: str) -> tuple[int, int]:
    a5 = quality()["A5_mobile_readability"]
    per_line = a5["caption_max_chars_per_line"]
    if lang in NO_SPACE_LANGS:
        per_line //= 2  # full-width glyphs
    return per_line, a5["caption_max_lines"]


def align_words(script: list[str], asr: list[tuple[str, float, float]]) -> list[tuple[float, float] | None]:
    """Map each script word to an ASR (start, end) via sequence matching; None when unmatched."""
    a = [normalise_for_wer(w) for w in script]
    b = [normalise_for_wer(w[0]) for w in asr]
    out: list[tuple[float, float] | None] = [None] * len(script)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = (asr[j1 + k][1], asr[j1 + k][2])
    return out


def _fill(times: list[tuple[float, float] | None], tokens: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Interpolate unmatched tokens between known anchors, weighted by character length."""
    n = len(tokens)
    res: list[tuple[float, float] | None] = list(times)
    i = 0
    while i < n:
        if res[i] is not None:
            i += 1
            continue
        j = i
        while j < n and res[j] is None:
            j += 1
        lo = res[i - 1][1] if i > 0 else start
        hi = res[j][0] if j < n else end
        hi = max(hi, lo + 0.05 * (j - i))
        wts = [max(1, len(t)) for t in tokens[i:j]]
        tot, cur = sum(wts), lo
        for k, wt in enumerate(wts):
            d = (hi - lo) * wt / tot
            res[i + k] = (cur, cur + d)
            cur += d
        i = j
    return res  # type: ignore[return-value]


def segment_cues(tokens: list[str], times: list[tuple[float, float]], lang: str) -> list[dict]:
    """Group timed tokens into cues of <= max_lines lines of <= max chars."""
    per_line, max_lines = limits(lang)
    j = joiner(lang)
    cues, lines, line, cs, ce = [], [], [], None, None

    def flush():
        nonlocal lines, line, cs, ce
        if line:
            lines.append(j.join(line))
        if lines:
            cues.append({"start": cs, "end": ce, "lines": lines})
        lines, line, cs, ce = [], [], None, None

    for tok, (a, b) in zip(tokens, times):
        cand = j.join(line + [tok])
        if line and len(cand) > per_line:
            lines.append(j.join(line))
            line = []
            if len(lines) >= max_lines:
                flush()
        line.append(tok)
        if cs is None:
            cs = a
        ce = b
    flush()
    return cues


def build_cues(m: dict, lang: str, seg_windows: dict[str, tuple[float, float]],
               asr_words: dict[str, list[tuple[str, float, float]]] | None = None) -> list[dict]:
    """Cues for every segment. seg_windows give (start, end) per segment id; asr_words (optional)
    are per-segment ASR words used to sharpen word timing (English master)."""
    cues = []
    for s in m["segments"]:
        a, b = seg_windows[s["id"]]
        toks = tokenise(seg_text(m, s, lang), lang)
        if not toks:
            continue
        known = align_words(toks, asr_words[s["id"]]) if asr_words and s["id"] in asr_words else [None] * len(toks)
        times = _fill(known, toks, a, b)
        # keep every word inside its segment window
        times = [(min(max(x, a), b), min(max(y, a), b)) for x, y in times]
        cues.extend(segment_cues(toks, times, lang))
    for i, c in enumerate(cues):  # no overlaps, minimum on-screen time
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + 1
        c["end"] = max(min(max(c["end"], c["start"] + 0.6), nxt), c["start"] + 0.2)
    return cues


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    mi, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    return "".join(f"{i}\n{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}\n" + "\n".join(c["lines"]) + "\n\n"
                   for i, c in enumerate(cues, 1))


def to_vtt(cues: list[dict]) -> str:
    return "WEBVTT\n\n" + "".join(f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n" + "\n".join(c["lines"]) + "\n\n"
                                  for c in cues)
