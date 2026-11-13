"""Sentence splitting with natural pause lengths by punctuation."""
from __future__ import annotations
import re
import numpy as np
from ..audio import Wav

PAUSE_S = {".": 0.42, "?": 0.48, "!": 0.40, "…": 0.55, ";": 0.30, ":": 0.30, ",": 0.16, "para": 0.80}
# Pacing hints: a marker placed in front of a sentence lengthens the pause before it, so the hook can land and the payoff
# arrives after a beat. `[[hook]]` = the hook ends before this sentence; `[[payoff]]` = the payoff starts at this sentence.
# The pause is a floor (max with the punctuation pause), never a cut. Markers are removed from the spoken text.
PACING_S = {"hook": 0.65, "payoff": 0.60, "pause": 0.50}
# `[[pause]]` (0.5 s) or `[[pause:0.8]]` (seconds, at most PAUSE_MAX_S) is an explicit pause at that point, also inside a
# sentence. `*word*` emphasis is screen markup (kinetic text): the asterisks are removed before TTS, never read out; no
# engine here takes an emphasis control, so emphasis stays visual.
PAUSE_MAX_S = 2.0
_MARK = re.compile(r"\[\[(hook|payoff|pause(?::\d+(?:\.\d+)?)?)\]\]")
_LEAD_MARK = re.compile(r"^\s*\[\[(hook|payoff|pause(?::\d+(?:\.\d+)?)?)\]\]\s*")
_INLINE_PAUSE = re.compile(r"\s*\[\[pause(?::(\d+(?:\.\d+)?))?\]\]\s*")
_EMPH = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")


def strip_emphasis(text: str) -> str:
    """`*word*` -> `word` (on-screen emphasis markup is never spoken)."""
    return _EMPH.sub(r"\1", text)


def _mark_seconds(m: str) -> float:
    if m.startswith("pause"):
        return min(PAUSE_MAX_S, float(m.split(":", 1)[1])) if ":" in m else PACING_S["pause"]
    return PACING_S[m]
MAX_WORDS = 25  # longer sentences are split at commas so the model stays stable
_END = "。！？।॥؟.!?…"
_TERM = {"。": ".", "！": "!", "？": "?", "।": ".", "॥": ".", "؟": "?"}
_COMMAS = ",，、،"
_SPLIT = re.compile(rf"(?<=[{re.escape(_END)}])\s+|(?<=[。！？])")
_ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e|No)\.$", re.I)
_DECIMAL = re.compile(r"\d[.,]$")


def strip_markers(text: str) -> str:
    """Remove pacing markers (for TTS paths that do not split sentences)."""
    text = re.sub(r"[ \t]*\[\[(?:hook|payoff|pause(?::\d+(?:\.\d+)?)?)\]\][ \t]*", " ", text)
    return strip_emphasis(re.sub(r"[ \t]*\[\[d:[A-Za-z_]+\]\][ \t]*", " ", text)).strip()


def mark_pacing(text: str, payoff_at: int | None = None) -> str:
    """Insert pacing markers into plain text: `[[hook]]` after the first sentence, and `[[payoff]]` before sentence index
    `payoff_at` (0-based; None = no payoff marker). Existing markers are left alone."""
    if _MARK.search(text):
        return text
    sents = [x for x in _SPLIT.split(" ".join(text.split())) if x.strip()]
    if len(sents) < 2:
        return text
    out = []
    for i, x in enumerate(sents):
        if i == 1:
            out.append("[[hook]]")
        elif payoff_at is not None and i == payoff_at and i > 1:
            out.append("[[payoff]]")
        out.append(x)
    return " ".join(out)


def _pause_for(s: str) -> float:
    s = s.rstrip()
    if s.endswith(("...", "…")):
        return PAUSE_S["…"]
    last = s[-1:] if s else "."
    last = _TERM.get(last, last)
    return PAUSE_S.get(last, PAUSE_S["."])


def split_sentences(text: str) -> list[tuple[str, float]]:
    """-> [(sentence, pause_after_seconds)]. Paragraph breaks (blank line) get the longer pause."""
    return [(t, p) for t, p, _ in split_marked(text)]


def split_marked(text: str) -> list[tuple[str, float, bool]]:
    """split_sentences plus a flag per piece: True when its pause comes from an explicit marker ([[hook]], [[payoff]],
    [[pause]]), which callers must keep (a short piece with an explicit pause is not merged into its neighbour)."""
    out: list[tuple[str, float, bool]] = []
    for pi, para in enumerate(p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()):
        para = " ".join(para.split())
        parts: list[str] = []
        for chunk in _SPLIT.split(para):
            chunk = chunk.strip()
            if not chunk:
                continue
            # a delivery marker at the start is a scene boundary: "4.84. [[d:signoff]] Follow..." is two sentences, not a decimal
            if parts and not chunk.startswith("[[d:") and (_ABBREV.search(parts[-1]) or _DECIMAL.search(parts[-1])):
                parts[-1] += " " + chunk
            else:
                parts.append(chunk)
        for s in parts:
            lead = _LEAD_MARK.match(s)
            while lead:
                s = s[lead.end():]
                if out:      # lengthen the pause after the previous sentence (floor, never shorter than its own)
                    out[-1] = (out[-1][0], max(out[-1][1], _mark_seconds(lead[1])), True)
                lead = _LEAD_MARK.match(s)
            if not s:
                continue
            bits = _INLINE_PAUSE.split(s)          # text, seconds|None, text, ...
            for k in range(0, len(bits), 2):
                seg = bits[k].strip()
                if not seg:
                    continue
                pieces = _split_long(seg)
                out += [(piece, pause, False) for piece, pause in pieces]
                if k + 1 < len(bits):
                    sec = min(PAUSE_MAX_S, float(bits[k + 1])) if bits[k + 1] else PACING_S["pause"]
                    out[-1] = (out[-1][0], max(out[-1][1] if out[-1][0][-1:] in _END else 0.0, sec), True)
        if out:
            out[-1] = (out[-1][0], max(PAUSE_S["para"], out[-1][1]) if out[-1][2] else PAUSE_S["para"], out[-1][2])
    if out:
        out[-1] = (out[-1][0], 0.0, False)
    return out


def _split_long(s: str) -> list[tuple[str, float]]:
    cjk = len(re.findall(r"[぀-ヿ一-鿿]", s)) > len(s) / 3
    n = len(s) / 2 if cjk else len(s.split())
    if n <= MAX_WORDS or not any(c in s for c in _COMMAS):
        return [(s, _pause_for(s))]
    pieces = re.split(rf"(?<=[{re.escape(_COMMAS)}])\s*", s)
    res, cur = [], ""
    for p in pieces:
        if not p:
            continue
        cur2 = (cur + " " + p).strip() if cur else p
        size = len(cur2) / 2 if cjk else len(cur2.split())
        if cur and size > MAX_WORDS * 0.6:
            res.append((cur, PAUSE_S[","])); cur = p
        else:
            cur = cur2
    if cur:
        res.append((cur, _pause_for(cur)))
    return res


def join_with_pauses(parts: list[tuple[Wav, float]]) -> Wav:
    """Concatenate sentence audio with the given pause (s) after each; sample rates must match."""
    if not parts:
        raise ValueError("nothing to join")
    sr = parts[0][0].sr
    chunks = []
    for w, pause in parts:
        if w.sr != sr:
            raise ValueError("sample-rate mismatch")
        chunks.append(w.samples)
        if pause > 0:
            chunks.append(np.zeros(int(pause * sr), dtype=np.float32))
    return Wav(np.concatenate(chunks).astype(np.float32), sr, parts[0][0].engine)
