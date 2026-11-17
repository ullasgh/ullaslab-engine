"""WP8: QA A5 (mobile readability) for studio renders, with the A5 limits of config/quality.yaml unchanged.

One still per timed scene (at 70% of its span) of each rendered output, with the layout audit on (remotion/studio_render.mjs
--audit-frames): element geometry, font size, colours and word counts only, never text. Same roles and limits as
qa.gate_a5: body roles (headline, body, caption, legal) at least min_body_text_px, label roles (label, axis, stamp, tag) at
least min_label_text_px, contrast at least min_contrast_ratio wherever foreground and background colours are known, at most
max_non_caption_words_per_scene words of headline, body and label text per still, and nothing outside the safe zone. The
safe zone is the renderer's own box (remotion/src/studio/layout.ts via layout_check, the stricter of YouTube Shorts and
Instagram Reels for 9:16): headlines, body, labels and stamps inside the content box (the safe box minus the caption band,
the rule the style stills follow), captions, the end card and the footage tag inside the safe box. Studio text set at label
size carries the `label` role (chart metric and unit lines, diagram and card details, kinetic subtitles)."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from . import FPS
from .layout_check import SIZES, caption_boxes
from ..config import quality
from ..qa import BODY_ROLES, COUNTED_ROLES, LABEL_ROLES, contrast_ratio
from .style_check import TOL

CONTENT_ROLES = ("headline", "body", "label", "axis", "stamp", "legal")
SAFE_ROLES = ("caption", "endcard", "tag")


def min_px() -> dict[str, float]:
    q = quality()["A5_mobile_readability"]
    return {**{r: q["min_body_text_px"] for r in BODY_ROLES}, **{r: q["min_label_text_px"] for r in LABEL_ROLES}}


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
    """Counts only (numbers, no text): frames, elements, outside, small_text, low_contrast, min_contrast, max_words, size_ok."""
    q = quality()["A5_mobile_readability"]
    b = caption_boxes(orientation, lines=1)
    sx0, sy0, sx1, sy1 = b["safe"]
    cx0, cy0, cx1, cy1 = b["content"]
    floors = min_px()
    outside = small = elements = low = fonts = font_missing = 0
    min_cr, max_words = 99.0, 0
    for fr in audit.get("frames", []):
        words = 0
        for f in fr.get("fonts", []):
            fonts += 1
            font_missing += not f.get("loaded")
        for e in fr.get("elements", []):
            role = e.get("role")
            if role not in CONTENT_ROLES + SAFE_ROLES:
                continue
            elements += 1
            x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"]
            bx0, by0, bx1, by1 = (cx0, cy0, cx1, cy1) if role in CONTENT_ROLES else (sx0, sy0, sx1, sy1)
            if x0 < bx0 - TOL or x1 > bx1 + TOL or y0 < by0 - TOL or y1 > by1 + TOL:
                outside += 1
            if role in floors and e.get("fontPx", 0) < floors[role] - 0.01:
                small += 1
            if e.get("fg") and e.get("bg"):
                cr = contrast_ratio(e["fg"], e["bg"])
                min_cr = min(min_cr, cr)
                low += cr < q["min_contrast_ratio"]
            if role in COUNTED_ROLES:
                words += int(e.get("words", 0))
        max_words = max(max_words, words)
    w, h = SIZES[orientation]
    return {"frames": len(audit.get("frames", [])), "elements": elements, "outside": outside, "small_text": small,
            "fonts": fonts, "font_missing": font_missing, "low_contrast": low, "min_contrast": round(min_cr, 3), "max_words": max_words,
            "size_ok": (audit.get("width"), audit.get("height")) == (w, h)}


def node_audit(props: Path, public: Path, frames: list[int], out: Path) -> dict:
    from .run import REMOTION, StudioError
    props, public, out = Path(props).resolve(), Path(public).resolve(), Path(out).resolve()   # node runs in remotion/
    cmd = ["node", str(REMOTION / "studio_render.mjs"), "--props", str(props), "--public", str(public),
           "--audit-frames", ",".join(map(str, frames)), "--audit-out", str(out)]
    r = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True)
    if r.returncode:
        raise StudioError(f"layout audit failed: {(r.stderr or r.stdout)[-600:]}")
    return json.loads(out.read_text())
