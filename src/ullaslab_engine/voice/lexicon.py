"""Editable pronunciation lexicon (config/lexicon.yaml) applied to script text before TTS.

Entries are whole-token matches (literal, case-sensitive unless `ci: true`) or regexes. A language section wins over `common`
for the same `match`; longer matches win over shorter ones. No match -> text unchanged. Override the file with the
ULLASLAB_LEXICON environment variable (tests, local experiments); a missing file means an empty lexicon."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from ..config import CONFIG_DIR

_TOKEN_CHARS = r"A-Za-z0-9_"
_cache: dict[tuple, list[tuple[re.Pattern, str, bool]]] = {}


def lexicon_path() -> Path:
    return Path(os.environ.get("ULLASLAB_LEXICON") or CONFIG_DIR / "lexicon.yaml")


def _pattern(e: dict) -> re.Pattern:
    flags = re.IGNORECASE if e.get("ci") else 0
    m = str(e["match"])
    if e.get("regex"):
        return re.compile(m, flags)
    body = re.escape(m)
    # whole token: do not match inside a longer alphanumeric run ("bp" inside "bps", "oz" inside "ozone")
    lead = rf"(?<![{_TOKEN_CHARS}])" if re.match(rf"[{_TOKEN_CHARS}]", m) else ""
    tail = rf"(?![{_TOKEN_CHARS}])" if re.search(rf"[{_TOKEN_CHARS}]$", m) else ""
    return re.compile(lead + body + tail, flags)


def validate(doc: dict) -> list[str]:
    """Problems in a parsed lexicon (empty list = fine). Used by the tests and safe to call from a CLI check."""
    errs = []
    if not isinstance(doc, dict):
        return ["lexicon is not a mapping"]
    for sec, entries in doc.items():
        if sec == "version":
            continue
        if not isinstance(entries, list):
            errs.append(f"{sec}: not a list")
            continue
        for i, e in enumerate(entries):
            if not isinstance(e, dict) or "match" not in e or "say" not in e:
                errs.append(f"{sec}[{i}]: needs match and say")
                continue
            try:
                _pattern(e)
            except re.error as x:
                errs.append(f"{sec}[{i}] {e['match']!r}: bad regex ({x})")
    return errs


def pronunciation_path() -> Path:
    return Path(os.environ.get("ULLASLAB_PRONUNCIATION") or CONFIG_DIR / "pronunciation.yaml")


def _spelled(say: str) -> bool:
    """True when `say` is made only of single capital letters ("C P I"): such a form also takes a plural ("C P Is")."""
    toks = say.split()
    return bool(toks) and all(len(t) == 1 and t.isalpha() and t.isupper() for t in toks)


# A dotted form ends its sentence at the end of a text, a line or before a pacing marker, or before a word that starts a sentence and
# hardly ever follows "U.S." inside one ("U.S. The Fed met"; "the U.S. Treasury" and "the U.S. Fed" keep running on).
_STARTERS = ("The", "A", "An", "It", "This", "That", "These", "Those", "But", "And", "So", "Then", "They", "We", "He", "She", "In", "On",
             "At", "As", "For", "If", "When", "While", "With", "Now", "Here", "There", "What", "Why", "How", "Some", "Many", "Most",
             "One", "Our", "Your", "Its", "Their", "Meanwhile", "However", "Yet", "Still", "Today", "Next")
_SENTENCE_END = r"(?=\s*(?:$|\n|\[\[)|\s+(?:" + "|".join(_STARTERS) + r")\b)"


def pronunciation_entries(doc: dict) -> list[dict]:
    """Lexicon entries for the English pronunciation list (config/pronunciation.yaml): `letters` are spoken as listed; a dotted
    key ("U.S.") also matches its bare form ("US") and, at the end of a text, keeps its full stop; a letters key that is spelled
    out also matches its plural ("ETFs", "ETF's") and speaks it as letters plus s; `words` are spoken as listed (explicit, so a
    word acronym is never spelled)."""
    letters = {str(k): str(v) for k, v in (doc.get("letters") or {}).items()}
    words = {str(k): str(v) for k, v in (doc.get("words") or {}).items()}
    out: list[dict] = []
    seen: set[str] = set()

    def add(match: str, say: str, **kw):
        if match not in seen:
            seen.add(match)
            out.append({"match": match, "say": say, **kw})
    for k, v in letters.items():
        if "." in k:                       # dotted: the stop at the very end of a text is the sentence's own
            out.append({"match": r"(?<![A-Za-z0-9_.])" + re.escape(k) + _SENTENCE_END, "say": v + ".", "regex": True})
        add(k, v)
    for k, v in letters.items():
        if "." in k:                       # bare form of a dotted key: "US" is spoken as letters too, but not the "US$" currency prefix
            bare = k.replace(".", "")
            if bare not in seen and bare not in letters:
                seen.add(bare)
                out.append({"match": rf"(?<![A-Za-z0-9_$&.]){re.escape(bare)}(?![A-Za-z0-9_$&])", "say": v, "regex": True})
    for k, v in list(letters.items()):
        bare = k.replace(".", "")
        if _spelled(v) and bare.isalpha():
            for suffix in ("s", "'s", "\u2019s"):
                add(bare + suffix, v + suffix)
    for k, v in words.items():
        add(k, v)
    return out


def _pronunciation_doc() -> dict:
    p = pronunciation_path()
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _compile(doc: dict, lang: str) -> list[tuple[re.Pattern, str, bool]]:
    merged: dict[tuple[str, bool, bool], dict] = {}
    for sec in ("common", lang):               # language entries override common ones with the same match
        for e in doc.get(sec) or []:
            merged[(str(e["match"]), bool(e.get("regex")), bool(e.get("ci")))] = e
    if lang == "en":                           # the pronunciation list wins over the lexicon for the same match
        for e in pronunciation_entries(_pronunciation_doc()):
            merged[(str(e["match"]), bool(e.get("regex")), bool(e.get("ci")))] = e
    vals = list(merged.values())
    ordered = [e for e in vals if e.get("regex")] + sorted((e for e in vals if not e.get("regex")), key=lambda e: -len(str(e["match"])))
    return [(_pattern(e), str(e["say"]), bool(e.get("regex"))) for e in ordered]    # regexes first (file order), then literals longest first


def entries_for(lang: str, path: Path | None = None) -> list[tuple[re.Pattern, str, bool]]:
    p = Path(path) if path else lexicon_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    try:
        pm = pronunciation_path().stat().st_mtime if lang == "en" else 0.0
    except OSError:
        pm = -1.0
    key = (str(p), mtime + pm, lang, str(pronunciation_path()) if lang == "en" else "")
    if key not in _cache:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        errs = validate(doc)
        if errs:
            raise ValueError(f"{p}: " + "; ".join(errs[:5]))
        _cache[key] = _compile(doc, lang)
    return _cache[key]


def apply_lexicon(text: str, lang: str, path: Path | None = None) -> str:
    """Replace lexicon matches. Each hit is parked behind a placeholder so a later entry cannot rewrite an earlier entry's
    output (e.g. USD -> "U S dollars" must not then be hit by a rule for "dollars"); placeholders are restored at the end."""
    ents = entries_for(lang, path)
    if not ents:
        return text
    parked: list[str] = []

    def park(say: str, is_regex: bool):
        def f(m: re.Match) -> str:
            parked.append(m.expand(say) if is_regex else say)
            return f"\x00{len(parked) - 1}\x00"
        return f
    for pat, say, is_regex in ents:
        text = pat.sub(park(say, is_regex), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m[1])], text)
