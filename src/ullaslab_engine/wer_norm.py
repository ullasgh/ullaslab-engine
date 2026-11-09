"""Text canonicalisation applied identically to the script (reference) and the ASR output (hypothesis)
before WER, so the gate measures mispronunciation and not spelling: 5.50 vs 5.5, % vs percent, 7th October vs
7 October, bps vs basis points, R B I vs RBI, hyphens and slashes."""
from __future__ import annotations
import re

from .bundle import normalise_for_wer
from .voice.textnorm import _EN_MONTH_IDX, _en_year, d_ord_en, normalize_text

_MONTH = "|".join(m.capitalize() for m in _EN_MONTH_IDX)
_MONTH_RE = rf"(?P<mon>(?:{_MONTH}|{'|'.join(m[:3].capitalize() for m in _EN_MONTH_IDX)})\.?)"
_DAY = r"(?P<d>\d{1,2})(?:st|nd|rd|th)?"
_FULL = {m[:3]: m for m in _EN_MONTH_IDX}
_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_DM = re.compile(rf"\b(?:[Tt]he )?{_DAY}(?: of)? {_MONTH_RE}(?:,? (?P<y>\d{{4}}))?\b", )
_RE_MD = re.compile(rf"\b{_MONTH_RE} {_DAY}(?:,? (?P<y>\d{{4}}))?\b")
_RE_TRAIL0 = re.compile(r"(?<![\d.])(\d+)\.(\d*?)0+(?![\d])")
_RE_ORD = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")


def _mon(s: str) -> str:
    k = s.rstrip(".").lower()[:3]
    return _FULL[k].capitalize()


def _spoken_date(d: str, mon: str, y: str | None) -> str:
    out = f"{d_ord_en(int(d))} of {_mon(mon)}"
    return out + (f" {_en_year(int(y))}" if y else "")


def _dates(t: str) -> str:
    t = _RE_ISO.sub(lambda m: _spoken_date(m[3], _MONTH_NAMES[int(m[2]) - 1], m[1]) if 1 <= int(m[2]) <= 12 else m[0], t)
    t = _RE_DM.sub(lambda m: _spoken_date(m["d"], m["mon"], m["y"]), t)
    return _RE_MD.sub(lambda m: _spoken_date(m["d"], m["mon"], m["y"]), t)


_MONTH_NAMES = [m.capitalize() for m in _EN_MONTH_IDX]


def _decimals(m: re.Match) -> str:
    return m[1] + ("." + m[2] if m[2] else "")


def _acronyms(tokens: list[str]) -> list[str]:
    out, run = [], []
    for w in tokens + [""]:
        if len(w) == 1 and w.isalpha():
            run.append(w)
            continue
        if run:
            out.extend(["".join(run)] if len(run) > 1 else run)
            run = []
        if w:
            out.append(w)
    return out


def canonical_for_wer(text: str, lang: str = "en") -> str:
    t = text.replace("’", "'")
    t = re.sub(r"\bper cent\b", "percent", t, flags=re.I)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s?(?:bps|bp)\b", r"\1 basis points", t, flags=re.I)
    t = re.sub(r"\b(?:bps|bp)\b", "basis points", t, flags=re.I)
    t = t.replace("&", " and ")
    t = _RE_TRAIL0.sub(_decimals, t)
    if lang == "en":
        t = _dates(t)
        t = _RE_ORD.sub(r"\1", t)
    t = normalize_text(t, lang, None)
    t = t.replace("-", " ").replace("/", " ")
    toks = normalise_for_wer(t).split()
    return " ".join(_acronyms(toks) if lang == "en" else toks)
