"""Per-line delivery: a fixed vocabulary of tags, the marker that carries one through the narration text, and the mapping from
tag to synthesis settings for the active profile (config/delivery.yaml).

Tags (what the line is doing for the viewer; chosen by the scriptwriter and director, validated by schemas/scenes.schema.json):
  hook     the opening line that earns the next five seconds
  tension  the open question or the case being set up
  reveal   the number or result the story was building to
  explain  plain mechanism or context (the baseline voice)
  caution  the counter-case, the limit, what would weaken the view
  signoff  the closing takeaway and the fixed sign-off

No tag = the global voice settings, exactly as before. `baseline` (the default profile) also ignores every tag.
The marker `[[d:<tag>]]` is written in front of a scene's narration by studio/actions.output_text and is never spoken, counted
as a word or shown. `[[d:neutral]]` resets to no tag (a scene without a tag between tagged ones)."""
from __future__ import annotations

import re

from ..config import _load

TAGS = ("hook", "tension", "reveal", "explain", "caution", "signoff")
NEUTRAL = "neutral"
DELIVERY_MARK = re.compile(r"[ \t]*\[\[d:([A-Za-z_]+)\]\][ \t]*")
FIELDS = ("exaggeration", "cfg_weight", "temperature", "tempo", "pause_before", "pause_after", "gain_db")
BOUNDS = {"exaggeration": (0.25, 0.9), "cfg_weight": (0.2, 0.7), "temperature": (0.5, 0.95), "tempo": (0.9, 1.1),
          "pause_before": (0.0, 0.7), "pause_after": (0.0, 0.7), "gain_db": (-3.0, 3.0)}


def marker(tag: str) -> str:
    return f"[[d:{tag}]]"


def strip_delivery(text: str) -> str:
    return DELIVERY_MARK.sub(" ", text)


def take_delivery(text: str, sticky: str | None = None) -> tuple[str, str | None, str | None]:
    """(clean text, tag for this piece, tag that stays active after it). A marker at the very start sets the tag of this piece;
    otherwise the piece takes the sticky tag. A marker later in the piece (a scene boundary inside a sentence) only changes
    the tag of the pieces after it, so a sentence is never cut in the middle. Unknown tags are dropped (the schema rejects them
    upstream); `neutral` clears the tag."""
    tag, after = sticky, sticky
    first = True
    for m in DELIVERY_MARK.finditer(text):
        t = m.group(1).lower()
        t = None if t == NEUTRAL else t if t in TAGS else after
        at_start = not text[:m.start()].strip()
        if at_start and first:
            tag = t
        after = t
        first = False
    return re.sub(r"\s{2,}", " ", strip_delivery(text)).strip(), tag, after


def profile_names() -> list[str]:
    return list((_load("delivery.yaml").get("profiles") or {}).keys())


def default_profile(lang: str | None = None) -> str:
    from ..config import language
    from .settings import voice_defaults
    name = voice_defaults().get("delivery_profile") or "baseline"
    if lang:
        name = language(lang).get("delivery_profile") or name
    return str(name)


def load_profile(name: str) -> dict[str, dict]:
    """tag -> validated settings for the profile; ValueError on an unknown profile, tag, field or an out-of-bounds value."""
    cfg = _load("delivery.yaml")
    profiles = cfg.get("profiles") or {}
    if name not in profiles:
        raise ValueError(f"unknown delivery profile {name!r} (have {sorted(profiles)})")
    out: dict[str, dict] = {}
    for tag, st in (profiles[name] or {}).items():
        if tag not in TAGS:
            raise ValueError(f"delivery profile {name}: unknown tag {tag!r}")
        st = dict(st or {})
        bad = set(st) - set(FIELDS)
        if bad:
            raise ValueError(f"delivery profile {name}.{tag}: unknown field(s) {sorted(bad)}")
        for k, v in st.items():
            lo, hi = BOUNDS[k]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= float(v) <= hi:
                raise ValueError(f"delivery profile {name}.{tag}.{k}={v!r} outside {lo}..{hi}")
            st[k] = float(v)
        out[tag] = st
    return out


def synth_overrides(tag: str | None, profile: dict[str, dict], *, cfg_forced: bool = False) -> dict:
    """The Chatterbox sampling settings this tag changes (absolute values); {} for no tag, no entry or the baseline."""
    st = profile.get(tag or "", {})
    out = {k: st[k] for k in ("exaggeration", "temperature") if k in st}
    if "cfg_weight" in st and not cfg_forced:
        out["effective_cfg_weight"] = st["cfg_weight"]
    return out
