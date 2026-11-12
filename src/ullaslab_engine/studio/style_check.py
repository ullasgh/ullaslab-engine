"""Programmatic checks for the video-style stills (V2 M2): size, not blank, and text inside the safe zones.

Input is what remotion/scripts/style-stills.mjs writes: PNG stills plus audit.json (element geometry and font sizes only,
never text). Safe zones come from layout_check (read from remotion/src/studio/layout.ts), so these checks move with the
renderer. Pure functions; the Remotion render itself is exercised by tests/test_style_stills.py (RUN_RENDER=1)."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .layout_check import SIZES, caption_boxes

TEXT_ROLES = ("headline", "body", "label", "stamp")
MIN_PX = {"headline": 36, "body": 36, "label": 36, "stamp": 36, "caption": 40}   # quality.yaml A5 floors (label/stamp 36)
TOL = 4.0   # px: sub-pixel and rounding slop (the existing vertical timeline sits 2 px past the box edge)


def blank(path: Path) -> str | None:
    """None when the still has real content; else why it looks blank (flat colour or almost no variation)."""
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    if a.std() < 6.0:
        return f"flat image (std {a.std():.1f})"
    lum = a.mean(axis=2)
    if (np.abs(lum - np.median(lum)) > 24).mean() < 0.004:
        return "less than 0.4% of pixels differ from the background"
    return None


def check_still(rec: dict, png: Path) -> list[str]:
    """Problems for one audit record (empty list = pass)."""
    bad: list[str] = []
    tag = f"{rec['style']} {rec['aspect']} f{rec['frame']}"
    orient = "horizontal" if rec["aspect"] == "16:9" else "vertical"
    w, h = SIZES[orient]
    if (rec["width"], rec["height"]) != (w, h):
        bad.append(f"{tag}: composition is {rec['width']}x{rec['height']}, expected {w}x{h}")
    if not png.is_file():
        return bad + [f"{tag}: still missing"]
    with Image.open(png) as im:
        if im.size != (w, h):
            bad.append(f"{tag}: png is {im.size[0]}x{im.size[1]}, expected {w}x{h}")
    why = blank(png)
    if why:
        bad.append(f"{tag}: blank still, {why}")
    b = caption_boxes(orient, lines=1)
    sx0, sy0, sx1, sy1 = b["safe"]
    cx0, cy0, cx1, cy1 = b["content"]
    texts = [e for e in rec["elements"] if e["role"] in TEXT_ROLES + ("caption",)]
    if not any(e["role"] in ("headline", "body", "label") for e in texts):
        bad.append(f"{tag}: no headline or body text found")
    for e in texts:
        x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]
        role = e["role"]
        if role == "caption":
            if x0 < sx0 - TOL or x1 > sx1 + TOL or y0 < sy0 - TOL or y1 > sy1 + TOL:
                bad.append(f"{tag}: caption leaves the safe box ({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f})")
        elif x0 < cx0 - TOL or x1 > cx1 + TOL or y0 < cy0 - TOL or y1 > cy1 + TOL:
            bad.append(f"{tag}: {role} text outside the content box ({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}) vs {b['content']}")
        if e["fontPx"] < MIN_PX[role] - 0.5:
            bad.append(f"{tag}: {role} font {e['fontPx']:.0f}px below {MIN_PX[role]}px")
    caps = [e for e in texts if e["role"] == "caption"]
    for e in caps:
        for o in texts:
            if o["role"] != "caption" and o["y"] + o["h"] > e["y"] + TOL and o["x"] < e["x"] + e["w"] and o["x"] + o["w"] > e["x"]:
                bad.append(f"{tag}: {o['role']} text overlaps the caption")
                break
    return bad


def check_dir(out: Path) -> list[str]:
    out = Path(out)
    recs = json.loads((out / "audit.json").read_text())
    bad: list[str] = []
    for r in recs:
        bad += check_still(r, out / r["file"])
    return bad


if __name__ == "__main__":
    import sys

    problems = check_dir(Path(sys.argv[1]))
    print("\n".join(problems) or "style stills ok")
    raise SystemExit(1 if problems else 0)
