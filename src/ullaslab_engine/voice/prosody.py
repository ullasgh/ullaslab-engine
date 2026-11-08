"""Sentence splitting with natural pause lengths by punctuation."""
from __future__ import annotations
import re
import numpy as np
from ..audio import Wav

PAUSE_S = {".": 0.42, "?": 0.48, "!": 0.40, "…": 0.55, ";": 0.30, ":": 0.30, ",": 0.16, "para": 0.80}
MAX_WORDS = 25  # longer sentences are split at commas so the model stays stable
_END = "。！？।॥؟.!?…"
_TERM = {"。": ".", "！": "!", "？": "?", "।": ".", "॥": ".", "؟": "?"}
_COMMAS = ",，、،"
_SPLIT = re.compile(rf"(?<=[{re.escape(_END)}])\s+|(?<=[。！？])")
_ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e|No)\.$", re.I)
_DECIMAL = re.compile(r"\d[.,]$")


def _pause_for(s: str) -> float:
    s = s.rstrip()
    if s.endswith(("...", "…")):
        return PAUSE_S["…"]
    last = s[-1:] if s else "."
    last = _TERM.get(last, last)
    return PAUSE_S.get(last, PAUSE_S["."])


def split_sentences(text: str) -> list[tuple[str, float]]:
    """-> [(sentence, pause_after_seconds)]. Paragraph breaks (blank line) get the longer pause."""
    out: list[tuple[str, float]] = []
    for pi, para in enumerate(p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()):
        para = " ".join(para.split())
        parts: list[str] = []
        for chunk in _SPLIT.split(para):
            chunk = chunk.strip()
            if not chunk:
                continue
            if parts and (_ABBREV.search(parts[-1]) or _DECIMAL.search(parts[-1])):
                parts[-1] += " " + chunk
            else:
                parts.append(chunk)
        for s in parts:
            for piece, pause in _split_long(s):
                out.append((piece, pause))
        if out:
            out[-1] = (out[-1][0], PAUSE_S["para"])
    if out:
        out[-1] = (out[-1][0], 0.0)
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
