"""Per-language voice settings = voice_defaults overlaid by the language entry in config/languages.yaml.

accent: native -> target-language prosody (Chatterbox cfg_weight forced to 0 for non-English targets,
        per upstream README: a clip in another language otherwise leaks its accent into the output)
accent: mine   -> keep the reference speaker's accent (cfg_weight as configured)
"""
from __future__ import annotations
from ..config import _load, language

FALLBACK_DEFAULTS = {
    "accent": "native", "ref_clip": 1, "speaker": 0,
    "exaggeration": 0.4, "temperature": 0.7, "cfg_weight": 0.5,
}
ACCENTS = ("native", "mine")


def voice_defaults() -> dict:
    return {**FALLBACK_DEFAULTS, **(_load("languages.yaml").get("voice_defaults") or {})}


def voice_settings(lang: str, overrides: dict | None = None) -> dict:
    cfg = language(lang)
    s = voice_defaults()
    for k in ("accent", "ref_clip", "speaker", "exaggeration", "temperature", "cfg_weight", "speakers"):
        if k in cfg:
            s[k] = cfg[k]
    s.update(overrides or {})
    if s["accent"] not in ACCENTS:
        raise ValueError(f"{lang}: accent must be one of {ACCENTS}")
    s["ref_clip"] = int(s["ref_clip"])
    if not 1 <= s["ref_clip"] <= 3:
        raise ValueError(f"{lang}: ref_clip must be 1..3")
    # Upstream guidance: non-English target + native accent => cfg_weight 0.
    s["effective_cfg_weight"] = 0.0 if (s["accent"] == "native" and lang != "en") else float(s["cfg_weight"])
    return s


def apply_choices(choices: dict) -> dict:
    """Validate an owner choices JSON {lang: {accent?, ref_clip?, speaker?}} against the configured languages."""
    out = {}
    for lang, c in choices.items():
        cfg = language(lang)
        bad = set(c) - {"accent", "ref_clip", "speaker"}
        if bad:
            raise ValueError(f"{lang}: unknown keys {sorted(bad)}")
        if "accent" in c and c["accent"] not in ACCENTS:
            raise ValueError(f"{lang}: accent must be native|mine")
        if "ref_clip" in c and int(c["ref_clip"]) not in (1, 2, 3):
            raise ValueError(f"{lang}: ref_clip must be 1..3")
        if "speaker" in c:
            n = len(cfg.get("speakers", [])) or 1
            if not 0 <= int(c["speaker"]) < n:
                raise ValueError(f"{lang}: speaker index out of range")
        out[lang] = {k: (c[k] if k == "accent" else int(c[k])) for k in c}
    return out
