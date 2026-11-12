"""WP8 safe-zone gate for studio renders (the studio counterpart of QA A5 `elements_outside_safe_zone`).

One still per scene (at 70% of its span) of each rendered output, with the layout audit on (remotion/studio_render.mjs
--audit-frames): element geometry and font sizes only, never text. Rules are the ones the style stills are held to
(style_check.check_still): headlines, body copy and source stamps stay inside the content box (the safe box minus the
caption band), captions, the end card and the footage tag stay inside the safe box. Text floors are the A5 ones from
config/quality.yaml: headlines and captions at least min_body_text_px (44), the studio's body lines (chart metric and unit
lines, end-card line, set at label size by design), stamps and the footage tag at least min_label_text_px (36).
The safe box is the renderer's own (remotion/src/studio/layout.ts via layout_check: the stricter of YouTube Shorts and
Instagram Reels for 9:16). Limits are 0, as for A5."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from . import FPS
from .layout_check import SIZES, caption_boxes
from ..config import quality
from .style_check import TOL

CONTENT_ROLES = ("headline", "body", "stamp")
SAFE_ROLES = ("caption", "endcard", "tag")


def min_px() -> dict[str, float]:
    q = quality()["A5_mobile_readability"]
    big, small = q["min_body_text_px"], q["min_label_text_px"]
    return {"headline": big, "caption": big, "body": small, "stamp": small, "tag": small}


def audit_frames(scenes: list[dict], frames_total: int) -> list[int]:
    """Frame at 70% of every timed scene (narration start_s/end_s), deduplicated and inside the video."""
    out: list[int] = []
    for sc in scenes:
        n = sc.get("narration") or {}
        a, b = n.get("start_s"), n.get("end_s")
        if a is None or b is None:
            continue
        f = min(frames_total - 1, max(0, int(round((a + 0.7 * (b - a)) * FPS))))
        if f not in out:
            out.append(f)
    return out


def check_audit(audit: dict, orientation: str) -> dict:
    """Counts only (numbers, no text): {frames, elements, outside, small_text}."""
    b = caption_boxes(orientation, lines=1)
    sx0, sy0, sx1, sy1 = b["safe"]
    cx0, cy0, cx1, cy1 = b["content"]
    floors = min_px()
    outside = small = elements = 0
    for fr in audit.get("frames", []):
        for e in fr.get("elements", []):
            role = e.get("role")
            if role not in CONTENT_ROLES + SAFE_ROLES:
                continue
            elements += 1
            x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]
            bx0, by0, bx1, by1 = (cx0, cy0, cx1, cy1) if role in CONTENT_ROLES else (sx0, sy0, sx1, sy1)
            if x0 < bx0 - TOL or x1 > bx1 + TOL or y0 < by0 - TOL or y1 > by1 + TOL:
                outside += 1
            if role in floors and e.get("fontPx", 0) < floors[role] - 0.5:
                small += 1
    w, h = SIZES[orientation]
    size_ok = (audit.get("width"), audit.get("height")) == (w, h)
    return {"frames": len(audit.get("frames", [])), "elements": elements, "outside": outside, "small_text": small,
            "size_ok": size_ok}


def node_audit(props: Path, public: Path, frames: list[int], out: Path) -> dict:
    from .run import REMOTION, StudioError
    cmd = ["node", str(REMOTION / "studio_render.mjs"), "--props", str(props), "--public", str(public),
           "--audit-frames", ",".join(map(str, frames)), "--audit-out", str(out)]
    r = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True)
    if r.returncode:
        raise StudioError(f"layout audit failed: {(r.stderr or r.stdout)[-600:]}")
    return json.loads(out.read_text())
