"""Assembly: resolve every scene's visual (footage via the asset ledger, charts via data_ref -> chart specs, other
types via the SceneRenderer defaults) and write one Remotion props file per output."""
from __future__ import annotations
import re
import copy
import json
import subprocess
from datetime import date
from pathlib import Path

from ..config import language
from . import FPS
from ..endline import END_CARD_S
from .captions import build_cues

ASPECT_SIZE = {"16:9": (1920, 1080, "horizontal"), "9:16": (1080, 1920, "vertical")}
CHART_FILES = ("chart_specs.json", "charts.resolved.json", "chart.json")
VISUAL_FILE = "visual_data.json"   # optional: data for map/globe/timeline/flow scenes, keyed by data_ref.ref or scene id
NUMBER_LOCALE = {"western": "en-US", "indian": "en-IN", "arabic_western": "en-US"}


class AssembleError(RuntimeError):
    pass


def _s(v) -> str:
    return v if isinstance(v, str) else (v.get("en") or next(iter(v.values()), "")) if isinstance(v, dict) else str(v or "")


# ------------------------------------------------------------------ charts
def load_chart_specs(item: Path) -> dict[str, dict]:
    for name in CHART_FILES:
        p = item / name
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("charts"), (list, dict)):
                raw = raw["charts"]
            if isinstance(raw, list):
                return {str(c.get("id") or c.get("chart_id")): c for c in raw if isinstance(c, dict)}
            if isinstance(raw, dict):
                if "type" in raw or "kind" in raw:   # a single chart
                    return {str(raw.get("claim_id") or "c1"): raw}
                return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {}


_STAMP_TAG = re.compile(r"\s*\[(?:LIVE|RECENT|LAGGED|EXPECTATION|INFERRED)\]\s*$")


def stamp_name(name: str) -> str:
    """The source stamp as a viewer sees it. The content repo's stamp ends with the freshness tag ("... As of 2026-11-09.
    [RECENT]"); the tag belongs to the data ledger (meta.freshness), never on screen (studio QC: no freshness labels)."""
    return _STAMP_TAG.sub("", name or "")


def to_kit_chart(ref: str, c: dict) -> dict:
    """Engine chart (type/series/source) or kit chart (kind/meta) -> kit ChartSceneData."""
    if "kind" in c and "meta" in c:
        return c
    if "source" in c and isinstance(c["source"], str) or ("type" not in c and "series" not in c):
        raise AssembleError(f"chart '{ref}' is an unresolved fetch spec; resolve it first (ullaslab editorial chart-check writes "
                            f"charts.resolved.json) so the engine gets series, source and freshness")
    src = c.get("source") or {}
    series = c.get("series") or []
    pts = series[0]["points"] if series else []
    xs = [p["x"] for p in pts]
    meta = {"metric": _s(c.get("title")), "unit": c.get("unit", ""), "period": f"{xs[0]} to {xs[-1]}" if xs else "",
            "source": {"name": stamp_name(src.get("name", "")), "as_of": src.get("as_of", "")}, "freshness": c.get("freshness", "RECENT")}
    if src.get("url"):
        meta["source"]["url"] = src["url"]
    dec = c.get("decimals", 1)
    t = c["type"]
    if t in ("line", "compare"):
        out = {"kind": "line", "meta": meta, "decimals": dec,
               "series": [{"name": _s(s.get("name")), "points": s["points"]} for s in series]}
        if c.get("annotations"):
            out["annotations"] = [{"x": a["x"], "label": _s(a["label"])} for a in c["annotations"]]
        return out
    if t == "bar":
        return {"kind": "bar", "meta": meta, "decimals": dec, "bars": [{"label": str(p["x"]), "value": p["y"]} for p in pts]}
    if t in ("counter", "delta"):
        val = c.get("value", pts[-1]["y"] if pts else 0)
        out = {"kind": "counter", "meta": meta, "decimals": dec, "value": val, "spark": [p["y"] for p in pts][-30:] or None}
        if c.get("prior") is not None:
            d = val - c["prior"]
            out["delta"] = {"text": f"{d:+.{dec}f} vs prior", "tone": "up" if d > 0 else "down" if d < 0 else "flat"}
        return {k: v for k, v in out.items() if v is not None}
    raise AssembleError(f"chart '{ref}': unsupported type '{t}'")


# ------------------------------------------------------------------ footage
PREP_VERSION = 1


def _prep_stamp(src: Path, seconds: float, w: int, h: int) -> str:
    import hashlib
    return json.dumps({"v": PREP_VERSION, "src": hashlib.sha256(src.read_bytes()).hexdigest(), "seconds": f"{seconds:.3f}",
                       "w": w, "h": h, "fps": FPS}, sort_keys=True)


def prepare_clip(src: Path, dst: Path, seconds: float, w: int, h: int) -> None:
    """Trim or loop to the scene length, cover-crop to the output size, 30 fps, no audio.
    Skipped when dst was already made from the same source bytes and parameters (sidecar <dst>.prep.json), so editing
    one scene does not re-encode every footage clip (and the per-scene render cache sees the same file)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    side = dst.with_suffix(".prep.json")
    stamp = _prep_stamp(src, seconds, w, h)
    if dst.is_file() and side.is_file() and side.read_text() == stamp:
        return
    side.unlink(missing_ok=True)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.3f}", "-vf", vf,
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise AssembleError(f"ffmpeg clip prep failed for {src.name}: {r.stderr[-300:]}")
    side.write_text(stamp)


def footage_credit(entry: dict) -> str:
    lic = entry.get("licence", {})
    if lic.get("attribution"):
        return lic["attribution"]
    who = entry.get("creator") or ""
    return f"{who} / {entry.get('provider', '')}".strip(" /")


def load_assets(item: Path) -> dict[tuple[str, str], dict]:
    p = item / "assets.json"
    if not p.is_file():
        return {}
    return {(a.get("output", "main"), a["scene"]): a for a in json.loads(p.read_text(encoding="utf-8")).get("assets", [])
            if not a["filename"].startswith("audio/")}


# ------------------------------------------------------------------ props
def default_visual(kind: str, text: str) -> dict | None:
    meta = {"source": {"name": "Natural Earth (public domain); illustrative", "as_of": date.today().strftime("%Y-%m")},
            "freshness": "INFERRED"}
    if kind == "map":
        return {"meta": meta, "focus": {"center": [20, 20], "zoom": 1.0}, "highlights": [], "routes": [], "labels": []}
    if kind == "globe":
        return {"meta": meta, "lon0": 20, "lonSpeed": 0.5, "lat": 18, "highlights": [], "routes": [], "labels": []}
    return None


STYLES = ("data-story", "creator-motion", "chalk-talk", "clean-tech")   # keep in sync with remotion/src/studio/styles.ts (tested)


def build_props(item: Path, doc: dict, output: dict, public: Path, *, lang: str = "en", allow_placeholder: bool = False,
                clip_prep=prepare_clip) -> tuple[dict, list[str]]:
    """Props for one output of the timed scenes document. Returns (props, warnings)."""
    w, h, orient = ASPECT_SIZE[output["aspect"]]
    name = output["output"]
    warns: list[str] = []
    charts = load_chart_specs(item)
    visuals = json.loads((item / VISUAL_FILE).read_text(encoding="utf-8")) if (item / VISUAL_FILE).is_file() else {}
    assets = load_assets(item)
    refs: dict = {}
    scenes = copy.deepcopy(output["scenes"])
    for sc in scenes:
        nar = sc["narration"]
        dur = nar["end_s"] - nar["start_s"] + 1.0     # + room for the next scene's transition overlap
        t, sid = sc["type"], sc["id"]
        text = sc.get("on_screen_text")
        if text and t != "kinetic":   # '|' line breaks and *emphasis* are kinetic-only markup
            text = sc["on_screen_text"] = text.replace("|", " ").replace("*", "")
        dr = sc.get("data_ref")
        if t == "chart":
            ref = dr["ref"]
            if ref not in charts:
                raise AssembleError(f"{name}/{sid}: data_ref '{ref}' not found in {'/'.join(CHART_FILES)}")
            refs[ref] = to_kit_chart(ref, charts[ref])
        elif t == "footage":
            a = assets.get((name, sid))
            ref = f"footage:{sid}"
            if a and (item / a["filename"]).is_file():
                rel = f"footage/{name}/{sid}.mp4"
                clip_prep(item / a["filename"], public / rel, dur, w, h)
                refs[ref] = {"src": rel, "credit": footage_credit(a), "illustrative": a.get("illustrative", True), "lang": lang}
            elif allow_placeholder:
                warns.append(f"{name}/{sid}: no footage in assets.json, placeholder plate used (preview only)")
                refs[ref] = {"credit": "", "illustrative": True}
            else:
                raise AssembleError(f"{name}/{sid}: no footage for this scene in assets.json (run the broll stage)")
            sc["data_ref"] = {"kind": "ledger", "ref": ref}
        else:
            ref = (dr or {}).get("ref") or f"auto:{sid}"
            data = visuals.get(ref) or visuals.get(sid) or default_visual(t, text or "")
            if data is None and t in ("timeline", "flow"):
                warns.append(f"{name}/{sid}: no {t} data in {VISUAL_FILE}; rendered as kinetic text")
                sc["type"] = t = "kinetic"
            elif data is None:
                data = {}
            if t != "kinetic":
                refs[ref] = data
                sc["data_ref"] = {"kind": "data_point", "ref": ref}
            else:
                # A kinetic scene (as written, or downgraded above for lack of visual data) renders its text only. Drop the
                # director's data_ref: the renderer rejects a data_ref that has no entry in refs ("data_ref ... not found").
                sc["data_ref"] = None
        if sc["type"] == "kinetic" and not text:
            sc["on_screen_text"] = " ".join(nar["text"].split()[:7]).rstrip(",;:")
            warns.append(f"{name}/{sid}: kinetic scene without on_screen_text, used the first words of the narration")
    cues = build_cues(scenes, lang)
    nf = language(lang).get("number_format", "western")
    total = max(1, round(scenes[-1]["narration"]["end_s"] * FPS))
    last = scenes[-1]["narration"]
    card_from = max(round(last["start_s"] * FPS), total - round(END_CARD_S * FPS))   # last END_CARD_S s, or the whole last scene if shorter
    if doc.get("style") in STYLES or any(sc.get("style") in STYLES for sc in scenes):   # styled charts need a source stamp
        for sc in scenes:
            r = (sc.get("data_ref") or {}).get("ref")
            if sc["type"] in ("chart", "timeline", "flow") and r in refs and not (refs[r].get("meta", {}).get("source", {}).get("name")):
                raise AssembleError(f"{name}/{sc['id']}: styled {sc['type']} scene needs a source name for its stamp (data-licensing gate)")
    props_style = {"style": doc["style"]} if doc.get("style") in STYLES else {}   # V2 M2: item style (a scene's own style rides in scenes[])
    for sc in scenes:   # an unknown per-scene style would only be ignored by the renderer; say so
        if sc.get("style") is not None and sc["style"] not in STYLES:
            warns.append(f"{name}/{sc['id']}: unknown style {sc['style']!r} ignored")
            del sc["style"]
    return {**props_style, "orientation": orient, "scenes": scenes, "refs": refs, "lang": lang, "numberLocale": NUMBER_LOCALE.get(nf, "en-US"),
            "captions": cues, "rtl": lang == "ar", "durationInFrames": total, "width": w, "height": h,
            "endCard": {"fromFrame": card_from, "durationInFrames": max(1, total - card_from)}}, warns
