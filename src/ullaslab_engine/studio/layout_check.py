"""Caption layout check from the Remotion layout numbers: captions must sit inside the safe box and never overlap the
content box that scenes lay out in (CAPTION_RESERVE keeps content above them). Numbers are read from remotion/src/studio/layout.ts."""
from __future__ import annotations
import re
from ..config import ROOT

SIZES = {"horizontal": (1920, 1080), "vertical": (1080, 1920)}
# keep in sync with StudioCaptions.tsx; 0.5 em is the measured average bold-sans glyph width
CAPTION_FONT = {"horizontal": 50, "vertical": 44}


def layout_numbers() -> tuple[dict, int]:
    src = (ROOT / "remotion" / "src" / "studio" / "layout.ts").read_text(encoding="utf-8")
    box = {}
    for o in ("horizontal", "vertical"):
        m = re.search(rf"{o}:\s*{{\s*top:\s*(\d+),\s*bottom:\s*(\d+),\s*left:\s*(\d+),\s*right:\s*(\d+)", src)
        box[o] = dict(zip(("top", "bottom", "left", "right"), map(int, m.groups())))
    return box, int(re.search(r"CAPTION_RESERVE\s*=\s*(\d+)", src).group(1))


PLATFORMS = ("both", "youtube_shorts", "instagram_reels")


def platform_box(orientation: str, platform: str = "both", profile: str = "organic") -> dict:
    """Safe box (top/bottom/left/right px). 'both' is the renderer's box (stricter of the two platforms, read from layout.ts).
    A named platform uses its template in config/safe_zones.json (vertical only); profile 'ad' swaps in the ad-overlay bottom."""
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}; one of {PLATFORMS}")
    base = layout_numbers()[0][orientation]
    if platform == "both" or orientation != "vertical":
        box = dict(base)
        if profile == "ad" and orientation == "vertical":
            import json
            tpl = json.loads((ROOT / "config" / "safe_zones.json").read_text(encoding="utf-8"))["platforms"]
            box["bottom"] = max(t.get("profiles", {}).get("ad", {}).get("bottom", t["bottom"]) for t in tpl.values())
        return box
    import json
    t = json.loads((ROOT / "config" / "safe_zones.json").read_text(encoding="utf-8"))["platforms"][platform]
    box = {k: int(t[k]) for k in ("top", "bottom", "left", "right")}
    if profile == "ad":
        box["bottom"] = int(t.get("profiles", {}).get("ad", {}).get("bottom", box["bottom"]))
    return box


def caption_boxes(orientation: str, lines: int = 2, platform: str = "both") -> dict:
    """{'safe', 'content', 'caption'} as (x0, y0, x1, y1). Caption height = lines x 1.28 line-height x font + 24 px padding."""
    reserve = layout_numbers()[1]
    w, h = SIZES[orientation]
    s = platform_box(orientation, platform)
    safe = (s["left"], s["top"], w - s["right"], h - s["bottom"])
    content = (safe[0], safe[1], safe[2], safe[3] - reserve)
    ch = round(lines * 1.28 * CAPTION_FONT[orientation] + 24)
    caption = (safe[0], safe[3] - ch, safe[2], safe[3])
    return {"safe": safe, "content": content, "caption": caption}


def check(orientation: str, cues: list[dict] | None = None, lines: int = 2, platform: str = "both") -> list[str]:
    b = caption_boxes(orientation, lines, platform)
    s, c, cap = b["safe"], b["content"], b["caption"]
    bad = []
    if not (cap[0] >= s[0] and cap[2] <= s[2] and cap[1] >= s[1] and cap[3] <= s[3]):
        bad.append("caption box leaves the safe area")
    if cap[1] < c[3]:
        bad.append(f"caption top {cap[1]} overlaps content bottom {c[3]}")
    font = CAPTION_FONT[orientation]
    for cue in cues or []:
        for ln in cue["lines"]:
            width = sum(len(w["w"]) + 1 for w in ln) * font * 0.5 + 52      # conservative bold-sans estimate + padding
            if width > s[2] - s[0]:
                bad.append(f"caption line wider than safe width ({width:.0f}px): {' '.join(w['w'] for w in ln)[:40]}")
    return bad
