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
_cache: dict[tuple[str, float, str], list[tuple[re.Pattern, str, bool]]] = {}


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


def _compile(doc: dict, lang: str) -> list[tuple[re.Pattern, str, bool]]:
    merged: dict[tuple[str, bool, bool], dict] = {}
    for sec in ("common", lang):               # language entries override common ones with the same match
        for e in doc.get(sec) or []:
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
    key = (str(p), mtime, lang)
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
