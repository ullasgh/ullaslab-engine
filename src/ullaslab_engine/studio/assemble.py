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
VISUAL_FILE = "visual_data.json"   # data for map/globe/timeline/flow scenes, keyed by '<output>/<scene id>', data_ref.ref or scene id; flow and timeline REQUIRE an entry
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


def infer_decimals(values: list) -> int:
    """Decimals a chart prints: the most places any value carries (1 to 3), so 4.88 is never shown as 4.9. An explicit `decimals` wins."""
    best = 1
    for v in values:
        txt = repr(float(v))
        if "e" in txt or "E" in txt:
            continue
        places = len(txt.split(".")[1].rstrip("0")) if "." in txt else 0
        best = max(best, min(3, places))
    return best


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
    dec = c["decimals"] if "decimals" in c else infer_decimals([p["y"] for s_ in series for p in s_["points"]])
    t = c["type"]
    if t in ("line", "compare"):
        out = {"kind": "line", "meta": meta, "decimals": dec, "settle": True,   # the tip value shows once the line has arrived

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


# ------------------------------------------------------------------ chart views (watchability)
VIEW_KEYS = {"window", "highlight", "point", "marks"}
MAX_MARKS = 3


def _xkey(x) -> str:
    """Sortable key for a series x: ISO dates (YYYY, YYYY-MM, YYYY-MM-DD) and plain numbers compare as strings."""
    return f"{x:012.4f}" if isinstance(x, (int, float)) else str(x)


def _fmt(v: float, dec: int) -> str:
    return f"{v:.{dec}f}"


def apply_chart_view(sid: str, kit: dict, view: dict) -> dict:
    """A scene's own view of a line chart: a zoomed window, a highlighted x-range, an annotated point the line stops at, and
    extra annotated marks. The values shown are read from the series, never typed: the tip value is the value at the end of the
    view, each mark carries its own value. Raises AssembleError (public-safe, no data in the message beyond ids and dates)."""
    at = f"{sid}: chart_view"
    if kit.get("kind") != "line":
        raise AssembleError(f"{at} needs a line chart, this chart is '{kit.get('kind')}'")
    extra = set(view) - VIEW_KEYS
    if extra:
        raise AssembleError(f"{at} has unknown key(s) {sorted(extra)}; allowed {sorted(VIEW_KEYS)}")
    series = kit["series"]
    if len(series) != 1:
        raise AssembleError(f"{at} supports a single-series line chart, this one has {len(series)}")
    pts = list(series[0]["points"])
    dec = kit.get("decimals", 1)
    win = view.get("window") or {}
    lo = _xkey(win["from"]) if win.get("from") is not None else None
    hi = _xkey(win["to"]) if win.get("to") is not None else None
    if lo is not None and hi is not None and lo > hi:
        raise AssembleError(f"{at} window starts after it ends")
    pts = [p for p in pts if (lo is None or _xkey(p["x"]) >= lo) and (hi is None or _xkey(p["x"]) <= hi)]
    if len(pts) < 2:
        raise AssembleError(f"{at} window holds {len(pts)} observation(s); a view needs at least 2 (widen the window)")
    have = {_xkey(p["x"]): p for p in pts}

    def at_obs(x, what: str) -> dict:
        k = _xkey(x)
        if k not in have:
            raise AssembleError(f"{at} {what} is not an observation date inside the window (use a date the series has a value for)")
        return have[k]

    marks = list(view.get("marks") or [])
    if len(marks) > MAX_MARKS:
        raise AssembleError(f"{at} has {len(marks)} marks; at most {MAX_MARKS}")
    point = view.get("point")
    if point is not None:
        end = at_obs(point["x"], "point")
        pts = [p for p in pts if _xkey(p["x"]) <= _xkey(end["x"])]
        if len(pts) < 2:
            raise AssembleError(f"{at} point leaves {len(pts)} observation(s); a view needs at least 2")
        marks = marks + [point]
    out = {**kit, "series": [{**series[0], "points": pts}], "includeZero": False, "settle": True}
    ann = []
    for m in marks:
        o = at_obs(m["x"], "mark")
        if _xkey(o["x"]) > _xkey(pts[-1]["x"]):
            raise AssembleError(f"{at} mark lies after the end of the view")
        ann.append({"x": o["x"], "label": " ".join(x for x in (str(m.get("label") or "").strip(), _fmt(o["y"], dec)) if x)})
    if ann:
        out["annotations"] = ann
    hl = view.get("highlight")
    if hl:
        a, b = _xkey(hl["from"]), _xkey(hl["to"])
        if a > b or a < _xkey(pts[0]["x"]) or b > _xkey(pts[-1]["x"]):
            raise AssembleError(f"{at} highlight must lie inside the view")
        out["highlight"] = {"from": hl["from"], "to": hl["to"], **({"label": hl["label"]} if hl.get("label") else {})}
    out["meta"] = {**kit["meta"], "period": f"{pts[0]['x']} to {pts[-1]['x']}"}
    out["marker"] = {"x": pts[-1]["x"], "y": pts[-1]["y"]}
    return out


# ------------------------------------------------------------------ visual data (flow / timeline) validation
def validate_visual(sid: str, kind: str, data) -> None:
    """Shape the renderer needs. A bad entry fails here, with the scene id, instead of crashing the renderer mid-video."""
    at = f"{sid}: {kind} data in {VISUAL_FILE}"
    if not isinstance(data, dict):
        raise AssembleError(f"{at} must be an object")
    if kind == "flow":
        nodes, edges = data.get("nodes"), data.get("edges")
        if not isinstance(nodes, list) or len(nodes) < 2 or not isinstance(edges, list) or not edges:
            raise AssembleError(f"{at} needs at least 2 nodes and 1 edge")
        ids = [n.get("id") for n in nodes if isinstance(n, dict)]
        if len(ids) != len(nodes) or len(set(ids)) != len(ids) or not all(isinstance(n.get("label"), str) and n["label"].strip() for n in nodes) \
                or not all(isinstance(n.get("level"), int) and n["level"] >= 0 for n in nodes):
            raise AssembleError(f"{at}: every node needs a unique id, a label and an integer level >= 0")
        levels = sorted({n["level"] for n in nodes})
        if levels != list(range(len(levels))):
            raise AssembleError(f"{at}: node levels must run 0..N without gaps")
        for e in edges:
            if not isinstance(e, dict) or e.get("from") not in ids or e.get("to") not in ids:
                raise AssembleError(f"{at}: every edge must join two node ids")
    elif kind == "timeline":
        ev = data.get("events")
        if not isinstance(ev, list) or len(ev) < 2 or not all(isinstance(e, dict) and e.get("when") and e.get("title") for e in ev):
            raise AssembleError(f"{at} needs at least 2 events, each with 'when' and 'title'")


def check_visuals(item: Path, doc: dict) -> list[str]:
    """Fail-fast problems for one timed or untimed scenes document, before anything long runs: every flow or timeline scene has valid
    data in visual_data.json (never silently turned into a text card) and every chart_view applies to its chart."""
    problems: list[str] = []
    vp = item / VISUAL_FILE
    try:
        visuals = json.loads(vp.read_text(encoding="utf-8")) if vp.is_file() else {}
    except ValueError:
        return [f"{VISUAL_FILE} is not valid JSON"]
    charts = load_chart_specs(item)
    for o in doc.get("outputs", []):
        for sc in o["scenes"]:
            sid, t = f"{o['output']}/{sc['id']}", sc["type"]
            ref = (sc.get("data_ref") or {}).get("ref") or f"auto:{sc['id']}"
            try:
                if t in ("flow", "timeline"):
                    data = visuals.get(sid) or visuals.get(ref) or visuals.get(sc["id"])
                    if data is None:
                        raise AssembleError(f"{sid}: {t} scene has no entry in {VISUAL_FILE} (its data_ref ref or its scene id); "
                                            f"add its data or change the scene type. The render stops here: a {t} scene is never turned into a text card")
                    validate_visual(sid, t, data)
                if sc.get("chart_view") is not None:
                    if t != "chart":
                        raise AssembleError(f"{sid}: chart_view is only for chart scenes")
                    cref = (sc.get("data_ref") or {}).get("ref")
                    if cref in charts:
                        apply_chart_view(sid, to_kit_chart(cref, charts[cref]), sc["chart_view"])
            except AssembleError as e:
                problems.append(str(e))
    return problems


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
            kit = to_kit_chart(ref, charts[ref])
            if sc.get("chart_view") is not None:
                # this scene's own view of the chart: its own refs entry, so two scenes can show different windows of one chart
                kit = apply_chart_view(f"{name}/{sid}", kit, sc["chart_view"])
                kit["revealFrames"] = max(24, min(80, round(dur * FPS * 0.6) - 10))
                ref = f"{ref}@{sid}"
                sc["data_ref"] = {"kind": "chart", "ref": ref}
            refs[ref] = kit
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
            data = visuals.get(f"{name}/{sid}") or visuals.get(ref) or visuals.get(sid) or default_visual(t, text or "")
            if data is None and t in ("timeline", "flow"):
                # No silent downgrade (watchability slice 1): a diagram without data used to become a text card and the video
                # looked like slides. Stop here, before the long render, and say which scene needs what.
                raise AssembleError(f"{name}/{sid}: {t} scene has no entry in {VISUAL_FILE} (its data_ref ref or its scene id); "
                                    f"add its data or change the scene type. The render stops here: a {t} scene is never turned into a text card")
            elif data is None:
                data = {}
            if t in ("timeline", "flow"):
                validate_visual(f"{name}/{sid}", t, data)
            if t != "kinetic":
                refs[ref] = data
                sc["data_ref"] = {"kind": "data_point", "ref": ref}
            else:
                # A kinetic scene renders its text only. Drop the director's data_ref: the renderer rejects a data_ref that
                # has no entry in refs ("data_ref ... not found").
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
