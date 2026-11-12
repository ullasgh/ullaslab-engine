"""Text canonicalisation applied identically to the script (reference) and the ASR output (hypothesis)
before WER, so the gate measures mispronunciation and not spelling: 5.50 vs 5.5, % vs percent, 7th October vs
7 October, bps vs basis points, R B I vs RBI, hyphens and slashes."""
from __future__ import annotations
import re

from .bundle import normalise_for_wer
from .voice.textnorm import _EN_MONTH_IDX, _en_year, d_ord_en

_MONTH = "|".join(m.capitalize() for m in _EN_MONTH_IDX)
_MONTH_RE = rf"(?P<mon>(?:{_MONTH}|{'|'.join(m[:3].capitalize() for m in _EN_MONTH_IDX)})\.?)"
_DAY = r"(?P<d>\d{1,2})(?:st|nd|rd|th)?"
_FULL = {m[:3]: m for m in _EN_MONTH_IDX}
_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_DM = re.compile(rf"\b(?:[Tt]he )?{_DAY}(?: of)? {_MONTH_RE}(?:,? (?P<y>\d{{4}}))?\b", )
_RE_MD = re.compile(rf"\b{_MONTH_RE} {_DAY}(?:,? (?P<y>\d{{4}}))?\b")
_RE_TRAIL0 = re.compile(r"(?<![\d.])(\d+)\.(\d*?)0+(?![\d])")
_RE_NUM = re.compile(r"\d+(?:\s?[.,]\s?\d+)+")
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


_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i >= 2}
_SCALES = {"thousand": 10**3, "million": 10**6, "billion": 10**9, "trillion": 10**12}


def _num_word(w: str) -> bool:
    return w in _UNITS or w in _TENS or w == "hundred" or w in _SCALES


def words_to_digits(tokens: list[str]) -> list[str]:
    """English: a spelled-out cardinal becomes one digit token ("one hundred and twelve" -> "112", "four point two five"
    -> "4.25" then "425" like any written decimal), so the script and the ASR compare equal whichever way either side
    wrote the number. Applied to both sides; a run that is not a well-formed number is split where it stops being one."""
    out: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        if not _num_word(tokens[i]):
            out.append(tokens[i])
            i += 1
            continue
        total = cur = 0
        frac = ""
        j = i
        while j < n:
            w = tokens[j]
            if w in _UNITS:
                v = _UNITS[w]
                if (v >= 10 and cur % 100) or (v < 10 and cur % 10):
                    break
                cur += v
            elif w in _TENS:
                if cur % 100:
                    break
                cur += _TENS[w]
            elif w == "hundred":
                if cur % 100 == 0 and cur:
                    break
                cur = (cur or 1) * 100
            elif w in _SCALES:
                total += (cur or 1) * _SCALES[w]
                cur = 0
            elif w == "and" and j + 1 < n and _num_word(tokens[j + 1]) and (cur >= 100 or total):
                pass
            elif w == "point" and j + 1 < n and tokens[j + 1] in _UNITS and _UNITS[tokens[j + 1]] < 10:
                k = j + 1
                while k < n and tokens[k] in _UNITS and _UNITS[tokens[k]] < 10:
                    frac += str(_UNITS[tokens[k]])
                    k += 1
                j = k
                break
            else:
                break
            j += 1
        out.append(str(total + cur) + frac)
        i = j
    return out


def canonical_for_wer(text: str, lang: str = "en") -> str:
    t = text.replace("’", "'")
    t = re.sub(r"\bper cent\b", "percent", t, flags=re.I)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s?(?:bps|bp)\b", r"\1 basis points", t, flags=re.I)
    t = re.sub(r"\b(?:bps|bp)\b", "basis points", t, flags=re.I)
    t = t.replace("&", " and ")
    t = re.sub(r"(?<=\d)\s?([.,])\s?(?=\d)", r"\1", t)  # "5 .50" -> "5.50"
    t = _RE_TRAIL0.sub(_decimals, t)
    if lang == "en":
        t = _dates(t)
        t = _RE_ORD.sub(r"\1", t)
    # numbers compare as digit strings: ASR renders 5.50 as 5.5, 5,50, "5 ,550" or 550 inconsistently, so a
    # number is one token with its separators removed, and a spelled-out number counts once, not per word
    t = _RE_NUM.sub(lambda m: re.sub(r"[\s.,]", "", m[0]), t)
    t = t.replace("-", " ").replace("/", " ")
    toks = normalise_for_wer(t).split()
    return " ".join(words_to_digits(_acronyms(toks)) if lang == "en" else toks)


def merge_compounds(ref: list[str], hyp: list[str]) -> tuple[list[str], list[str]]:
    """'sebi sec' vs 'sebisec': an adjacent token pair on one side that equals one token on the other is
    the same word spelled with or without a separator."""
    def merge(a: list[str], other: set[str]) -> list[str]:
        out, i = [], 0
        while i < len(a):
            if i + 1 < len(a) and a[i] + a[i + 1] in other:
                out.append(a[i] + a[i + 1])
                i += 2
            else:
                out.append(a[i])
                i += 1
        return out
    return merge(ref, set(hyp)), merge(hyp, set(ref))
