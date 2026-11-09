"""Word timings from the TTS voice track and mapping onto scenes.json narration spans.

One interface, two backends: mlx-whisper (Apple Silicon, large-v3-turbo) locally; faster-whisper (CI/Linux).
Alignment is text based (normalised numbers/punctuation, then fuzzy matching), so ASR slips do not break scene timing.
Coverage below MIN_COVERAGE fails loudly (CoverageError)."""
from __future__ import annotations
import difflib
import platform
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import FPS

MIN_COVERAGE = 0.95
MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
TAIL_S = 0.6            # silence after the last word before the video ends
Word = tuple[str, float, float]


class CoverageError(RuntimeError):
    pass


# ---------------------------------------------------------------- ASR backends
def mlx_available() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_mlx(path: Path, lang: str) -> list[Word]:
    import mlx_whisper
    r = mlx_whisper.transcribe(str(path), path_or_hf_repo=MLX_MODEL, word_timestamps=True, language=lang,
                               condition_on_previous_text=False, verbose=None)
    return [(w["word"].strip(), float(w["start"]), float(w["end"])) for s in r["segments"] for w in s.get("words", [])
            if w["word"].strip()]


def transcribe_faster(path: Path, lang: str) -> list[Word]:
    from ..asr import transcribe
    return transcribe(path, lang)


def transcribe_words(path: Path, lang: str = "en", backend: str = "auto") -> tuple[list[Word], str]:
    """Return (words, backend used). auto = mlx-whisper when available, else faster-whisper."""
    use = backend if backend != "auto" else ("mlx" if mlx_available() else "faster")
    return (transcribe_mlx(path, lang) if use == "mlx" else transcribe_faster(path, lang)), use


# ---------------------------------------------------------------- normalisation
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _spell(m: re.Match) -> str:
    from num2words import num2words
    s = m.group(0).replace(",", "")
    try:
        if "." in s:
            whole, frac = s.split(".", 1)
            return f" {num2words(int(whole or 0))} point {' '.join(num2words(int(c)) for c in frac)} "
        return f" {num2words(int(s))} "
    except Exception:
        return f" {s} "


def norm_tokens(word: str) -> list[str]:
    """One printed word -> comparable tokens. '5.25%' -> five point two five percent; punctuation/case/accents dropped."""
    w = word.replace("%", " percent ").replace("$", " dollars ").replace("&", " and ").replace("’", "'")
    w = _NUM.sub(_spell, w)
    w = unicodedata.normalize("NFKD", w)
    w = "".join(c for c in w if not unicodedata.combining(c)).lower()
    w = re.sub(r"[^\w\s']|_", " ", w).replace("'", "")
    return w.split()


def _flat(words: list[str]) -> tuple[list[str], list[int]]:
    toks, owner = [], []
    for i, w in enumerate(words):
        for t in norm_tokens(w) or []:
            toks.append(t)
            owner.append(i)
    return toks, owner


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- alignment
@dataclass
class Aligned:
    times: list[tuple[float, float]]   # per script word
    matched: list[bool]                # per script word: anchored to an ASR word
    coverage: float


def align(script: list[str], asr: list[Word], start: float = 0.0, end: float | None = None) -> Aligned:
    """Time every script word. Anchors: exact normalised token matches, then fuzzy pairs (ratio >= 0.72) inside
    replaced blocks. Unanchored words are interpolated between anchors by character weight."""
    st, owner = _flat(script)
    at, a_owner = [], []
    for j, (w, _, _) in enumerate(asr):
        for t in norm_tokens(w):
            at.append(t)
            a_owner.append(j)
    hit: dict[int, list[int]] = {}   # script word idx -> asr word idxs
    sm = difflib.SequenceMatcher(None, st, at, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                hit.setdefault(owner[i1 + k], []).append(a_owner[j1 + k])
        elif tag == "replace":
            jlo = j1
            for i in range(i1, i2):          # monotonic greedy fuzzy pairing
                best, bj = 0.0, -1
                for j in range(jlo, j2):
                    s = _sim(st[i], at[j])
                    if s > best:
                        best, bj = s, j
                if best >= 0.72:
                    hit.setdefault(owner[i], []).append(a_owner[bj])
                    jlo = bj + 1
    n = len(script)
    times: list[tuple[float, float] | None] = [None] * n
    for i, js in hit.items():
        times[i] = (min(asr[j][1] for j in js), max(asr[j][2] for j in js))
    matched = [t is not None for t in times]
    # monotonic repair: an anchor earlier than its predecessor is dropped
    last = -1.0
    for i in range(n):
        if times[i] is not None:
            if times[i][0] < last - 1e-6:
                times[i], matched[i] = None, False
            else:
                last = times[i][0]
    total_end = end if end is not None else (asr[-1][2] if asr else start + 0.3 * n)
    out = _interpolate(times, script, start, total_end)
    return Aligned(out, matched, sum(matched) / n if n else 1.0)


def _interpolate(times, words, start, end):
    n = len(times)
    res = list(times)
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
        wts = [max(1, len(w)) for w in words[i:j]]
        cur = lo
        for k, wt in enumerate(wts):
            d = (hi - lo) * wt / sum(wts)
            res[i + k] = (cur, cur + d)
            cur += d
        i = j
    # enforce start <= end and monotonic non-overlap
    fixed, prev = [], 0.0
    for a, b in res:
        a = max(a, prev)
        b = max(b, a + 0.02)
        fixed.append((a, b))
        prev = a
    return fixed


# ---------------------------------------------------------------- scenes.json
def script_words(text: str) -> list[str]:
    return text.split()


UNSPACED = {"ja", "zh"}


def time_output(scenes: list[dict], asr: list[Word], total_s: float | None = None, label: str = "", lang: str = "en") -> dict:
    """Fill narration.start_s/end_s/words on one output's scenes (in place). Returns a stats dict.
    Scene boundaries are contiguous: a scene starts at its first word and runs to the next scene's first word."""
    words: list[str] = []
    span: list[tuple[int, int]] = []
    for sc in scenes:
        ws = script_words(sc["narration"]["text"])
        span.append((len(words), len(words) + len(ws)))
        words += ws
    if not words:
        raise CoverageError(f"{label}: no narration text")
    al = align(words, asr, 0.0, total_s)
    if al.coverage < MIN_COVERAGE:
        miss = [words[i] for i, m in enumerate(al.matched) if not m][:12]
        raise CoverageError(f"{label}: word coverage {al.coverage:.1%} below {MIN_COVERAGE:.0%} "
                            f"({sum(not m for m in al.matched)}/{len(words)} unmatched, e.g. {miss})"
                            + (f"; '{lang}' is written without spaces and word alignment does not support it yet (known limit, docs/studio.md)" if lang in UNSPACED else ""))
    last_end = max(b for _, b in al.times)
    total = max(total_s or 0.0, last_end + TAIL_S)
    for k, (sc, (a, b)) in enumerate(zip(scenes, span)):
        ws = [{"w": words[i], "start": round(al.times[i][0], 3), "end": round(al.times[i][1], 3)} for i in range(a, b)]
        sc["narration"]["words"] = ws
        sc["narration"]["start_s"] = 0.0 if k == 0 else ws[0]["start"] if ws else None
    for k, sc in enumerate(scenes):
        nxt = scenes[k + 1]["narration"]["start_s"] if k + 1 < len(scenes) else total
        sc["narration"]["end_s"] = round(nxt, 3)
    return {"coverage": round(al.coverage, 4), "words": len(words), "total_s": round(total, 3)}


def frame_ranges(scenes: list[dict], fps: int = FPS) -> list[tuple[int, int]]:
    """Contiguous integer frame ranges [start, end) from narration.start_s/end_s."""
    out, cursor = [], 0
    for sc in scenes:
        n = sc["narration"]
        b = round(n["end_s"] * fps)
        out.append((cursor, max(cursor + 1, b)))
        cursor = out[-1][1]
    return out
