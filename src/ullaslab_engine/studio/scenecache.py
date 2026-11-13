"""Per-scene render cache: render each scene's frame span of an output to its own clip, join the clips, and never render an
unchanged span again.

How the video is cut
  The renderer (remotion/src/studio/SceneRenderer.tsx) places scene i as a Sequence from `start_i` that lasts until
  `end_i + overlapAfter(i)` (the next scene's enter transition crosses over it). Segments are the half-open frame spans
  between consecutive scene starts ([0, start_0) is a lead segment when the first scene starts late; the last segment runs
  to durationInFrames). A segment is rendered from the FULL StudioVideo composition with Remotion's frameRange, so every
  frame is the frame a full render would draw: transitions, the outgoing scene under a crossfade, burned-in captions and
  the end card are all there. Nothing is re-composited in ffmpeg, so no neighbouring scene has to be re-rendered to keep a
  transition exact: a segment's key simply includes every scene visible in it.

What the cache key covers (anything that can change a segment's pixels)
  - the segment's absolute frame span and the composition length (absolute positions: a timing change re-renders, which
    is the safe choice: a shifted scene is never reused)
  - every scene visible in the span: its index (the first scene never transitions in), its normalised frame range
    including the overlap it is extended by, the scene object exactly as rendered (type, text, camera, transition, style,
    palette, data_ref, narration timing and words), the data its data_ref resolves to, and the sha256 of every public file
    that data names (footage clips)
  - item style, orientation, width/height, scale (preview vs final), fps, language, number locale, RTL, platform
  - caption cues that overlap the span (0.5 s margin) and the end card when it overlaps the span
  - a renderer stamp: sha256 of every file under remotion/src and remotion/public, remotion/studio_render.mjs,
    remotion/package.json and package-lock.json (Remotion, Chrome and encoder versions), the engine version and
    CACHE_VERSION. Any component change therefore invalidates every clip.

Joining
  Segment clips are H.264 High / yuv420p / 30 fps encoded without B-frames (-bf 0, set by studio_render.mjs), so the
  ffmpeg concat demuxer can stream-copy them with exact timestamps: no frame is dropped or repeated at a boundary (a
  B-frame stream concatenated this way repeats a frame at short boundaries; see tests/test_scenecache.py). The joined
  file must have exactly durationInFrames frames or the join fails. Audio is mixed once over the joined video by the mix
  stage, so it cannot drift per segment.

Safety
  A cached clip is used only if its file exists and ffprobe confirms the expected frame count, size, codec and no
  B-frames; otherwise it is deleted and rendered again. New clips are written to a temporary name and moved into place
  after the same check. The cache lives in <item>/work/scene_cache (never committed: work/ is git-ignored), with an LRU
  size bound (ULLASLAB_SCENE_CACHE_MAX_MB, default 4096) that never deletes a clip the current run uses."""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from ..config import ROOT
from . import FPS

CACHE_VERSION = 1
REMOTION = ROOT / "remotion"
# Mirrors remotion/src/studio/scenes.ts TRANSITION_FRAMES and director.ts TRANSITION_MAP (parity: tests/fixtures/scene_frames.json,
# checked by tests/test_scenecache.py and remotion/scripts/studio.test.mjs against the TypeScript).
TRANSITION_FRAMES = {"cut": 0, "crossfade": 12, "wipe": 14, "match_move": 16, "push_through": 20, "morph": 20, "sweep": 16, "interrupt": 8}
TRANSITION_MAP = {"cut": "cut", "crossfade": "crossfade", "wipe": "wipe", "match_cut": "match_move", "push": "match_move",
                  "dip_to_black": "crossfade", "pattern_interrupt": "cut"}
# Premium style: the director names map onto the premium transitions (premium/PremiumEnter.tsx), mirrors director.ts PREMIUM_TRANSITION_MAP.
PREMIUM_TRANSITION_MAP = {"cut": "cut", "crossfade": "crossfade", "wipe": "sweep", "match_cut": "morph", "push": "push_through",
                          "dip_to_black": "crossfade", "pattern_interrupt": "interrupt"}
CAPTION_MARGIN_S = 0.5
DEFAULT_MAX_MB = 4096
_KEY_RE = re.compile(r"[0-9a-f]{64}")


class SceneCacheError(RuntimeError):
    pass


# ------------------------------------------------------------------ frame plan (mirror of the TypeScript)
def js_round(x: float) -> int:
    """JavaScript Math.round (halves round up), not Python's banker's rounding."""
    return math.floor(x + 0.5)


def _kit_transition(sc: dict, item_style: str | None = None) -> str:
    t = sc.get("transition") or "cut"
    if "narration" in sc:                # director scene -> kit transition; a scene's own style wins over the item's (premium maps differently)
        style = sc.get("style") or item_style
        return (PREMIUM_TRANSITION_MAP if style == "premium" else TRANSITION_MAP).get(t, "cut")
    return t if t in TRANSITION_FRAMES else "cut"


def frame_plan(scenes: list[dict], fps: int = FPS, fallback_s: float = 3.0, style: str | None = None) -> list[dict]:
    """[{id, index, start, end, until}] with `until` = end + overlapAfter (the frame the scene's Sequence stops drawing).
    Same arithmetic as fromDirectorScenes + overlapAfter in the renderer."""
    out, cursor = [], 0
    director = bool(scenes) and "narration" in scenes[0]
    for i, sc in enumerate(scenes):
        if director:
            a, b = sc["narration"].get("start_s"), sc["narration"].get("end_s")
            num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
            start = js_round(a * fps) if num(a) else cursor
            end = max(start + 1, js_round(b * fps)) if num(b) else start + js_round(fallback_s * fps)
            cursor = end
        else:
            start, end = int(sc["start"]), int(sc["end"])
        out.append({"id": sc["id"], "index": i, "start": start, "end": end})
    for i, p in enumerate(out):
        nxt = scenes[i + 1] if i + 1 < len(scenes) else None
        p["until"] = p["end"] + (TRANSITION_FRAMES[_kit_transition(nxt, style)] if nxt else 0)
    return out


def segments(plan: list[dict], total: int) -> list[dict]:
    """Half-open frame spans [from, to) between scene starts, covering [0, total) exactly once.
    Each carries the indexes of the scenes visible in it (the scene that starts it, plus any earlier scene still drawing)."""
    if total < 1:
        raise SceneCacheError("durationInFrames must be at least 1")
    cuts = sorted({0, *(p["start"] for p in plan if 0 < p["start"] < total)})
    bounds = cuts + [total]
    segs = []
    for a, b in zip(bounds, bounds[1:]):
        vis = [p["index"] for p in plan if p["start"] < b and p["until"] > a]
        owners = [p["id"] for p in plan if p["start"] == a or (a == 0 and p["start"] < 0)] or ["_lead"]
        segs.append({"name": "+".join(owners), "from": a, "to": b, "visible": vis})
    return segs


# ------------------------------------------------------------------ key
def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_version() -> str:
    try:
        from importlib.metadata import version
        return version("ullaslab-engine")
    except Exception:  # noqa: BLE001 - source checkout without install metadata
        m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "unknown"


@functools.lru_cache(maxsize=4)
def renderer_stamp(remotion: Path = REMOTION) -> str:
    """Changes whenever a Remotion component, font, the render script, a pinned package or the engine version changes."""
    h = hashlib.sha256(f"scene-cache-v{CACHE_VERSION}|engine {engine_version()}".encode())
    files = [remotion / "studio_render.mjs", remotion / "package.json", remotion / "package-lock.json"]
    for sub in ("src", "public"):
        d = remotion / sub
        if d.is_dir():
            files += [p for p in d.rglob("*") if p.is_file()]
    for p in sorted(set(files)):
        if p.is_file():
            h.update(str(p.relative_to(remotion)).encode() + b"\0" + _file_sha(p).encode())
    return h.hexdigest()


def _public_files(data, public: Path) -> dict[str, str]:
    """sha256 of every string in a scene's data that names a file in the render's public dir (footage clips)."""
    out: dict[str, str] = {}
    root = public.resolve()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o and "/" in o and not o.startswith(("http://", "https://")) and len(o) < 512:
            p = public / o
            try:
                if p.is_file() and root in p.resolve().parents:
                    out[o] = _file_sha(p)
            except OSError:
                pass
    walk(data)
    return out


def _scene_data(sc: dict, refs: dict):
    if sc.get("data") is not None:
        return sc["data"]
    dr = sc.get("data_ref")
    ref = dr.get("ref") if isinstance(dr, dict) else dr
    return refs.get(ref) if ref else None


GLOBAL_KEYS = ("orientation", "width", "height", "lang", "numberLocale", "rtl", "style", "platform", "durationInFrames")
OPTIONAL_KEYS = ("brandMark",)     # in the key only when present, so keys of items without them are unchanged


def global_material(props: dict) -> dict:
    return {**{k: props.get(k) for k in GLOBAL_KEYS}, **{k: props[k] for k in OPTIONAL_KEYS if k in props}}


def segment_key(props: dict, plan: list[dict], seg: dict, *, public: Path, scale: float, renderer: str) -> str:
    a, b = seg["from"], seg["to"]
    refs = props.get("refs") or {}
    scenes = []
    for j in seg["visible"]:
        sc = props["scenes"][j]
        data = _scene_data(sc, refs)
        p = plan[j]
        scenes.append({"index": j, "first": j == 0, "frames": [p["start"], p["end"], p["until"]], "scene": sc, "data": data,
                       "files": _public_files(data, public)})
    lo, hi = a / FPS - CAPTION_MARGIN_S, b / FPS + CAPTION_MARGIN_S
    cues = [c for c in props.get("captions") or [] if c["end"] > lo and c["start"] < hi]
    card = props.get("endCard")
    if card and not (card["fromFrame"] < b and card["fromFrame"] + max(1, card["durationInFrames"]) > a):
        card = None
    material = {"v": CACHE_VERSION, "renderer": renderer, "comp": "StudioVideo", "fps": FPS, "scale": float(scale),
                "global": global_material(props), "range": [a, b], "scenes": scenes, "captions": cues,
                "endCard": card}
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ------------------------------------------------------------------ probing
def probe_video(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-print_format", "json", "-show_streams", "-show_format",
                        str(path)], capture_output=True, text=True)
    if r.returncode:
        raise SceneCacheError(f"ffprobe failed for {path.name}: {r.stderr[-200:]}")
    d = json.loads(r.stdout)
    if not d.get("streams"):
        raise SceneCacheError(f"{path.name}: no video stream")
    v = d["streams"][0]
    return {"frames": int(v.get("nb_frames") or 0), "width": int(v["width"]), "height": int(v["height"]), "codec": v["codec_name"],
            "pix_fmt": v.get("pix_fmt"), "rate": v.get("r_frame_rate"), "b_frames": int(v.get("has_b_frames") or 0),
            "duration": float(v.get("duration") or d.get("format", {}).get("duration") or 0)}


def clip_problems(path: Path, frames: int, w: int, h: int) -> list[str]:
    try:
        v = probe_video(path)
    except (SceneCacheError, ValueError, KeyError) as e:
        return [str(e)]
    bad = []
    if v["frames"] != frames:
        bad.append(f"{v['frames']} frames, expected {frames}")
    if (v["width"], v["height"]) != (w, h):
        bad.append(f"size {v['width']}x{v['height']}, expected {w}x{h}")
    if v["codec"] != "h264" or v["pix_fmt"] != "yuv420p" or v["rate"] != f"{FPS}/1":
        bad.append(f"format {v['codec']}/{v['pix_fmt']}/{v['rate']}")
    if v["b_frames"]:
        bad.append("has B-frames (a stream-copy join would not be frame exact)")
    return bad


# ------------------------------------------------------------------ cache store
def max_bytes_default() -> int:
    try:
        return int(float(os.environ.get("ULLASLAB_SCENE_CACHE_MAX_MB", DEFAULT_MAX_MB)) * 1024 * 1024)
    except ValueError:
        return DEFAULT_MAX_MB * 1024 * 1024


class SceneCache:
    """Content-addressed clip store: <root>/<sha256>.mp4 plus index.json (size, frames, last use, label)."""

    def __init__(self, root: Path, max_bytes: int | None = None):
        self.root = Path(root)
        self.max_bytes = max_bytes_default() if max_bytes is None else max_bytes
        self.index_path = self.root / "index.json"
        try:
            self.index = json.loads(self.index_path.read_text()) if self.index_path.is_file() else {}
        except (OSError, ValueError):
            self.index = {}          # a damaged index only costs re-renders; clips are re-validated on use anyway

    def path(self, key: str) -> Path:
        if not _KEY_RE.fullmatch(key):
            raise SceneCacheError(f"bad cache key {key!r}")
        return self.root / f"{key}.mp4"

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, indent=1, sort_keys=True))
        tmp.replace(self.index_path)

    def get(self, key: str, frames: int, w: int, h: int) -> Path | None:
        p = self.path(key)
        if not p.is_file():
            self.index.pop(key, None)
            return None
        if clip_problems(p, frames, w, h):       # damaged or partial clip: never serve it
            p.unlink(missing_ok=True)
            self.index.pop(key, None)
            return None
        rec = self.index.setdefault(key, {"bytes": p.stat().st_size, "frames": frames})
        rec["last_used"] = time.time()
        return p

    def put(self, key: str, tmp: Path, frames: int, w: int, h: int, label: str) -> Path:
        bad = clip_problems(tmp, frames, w, h) if tmp.is_file() else ["renderer wrote no clip"]
        if bad:
            tmp.unlink(missing_ok=True)
            raise SceneCacheError(f"rendered clip for {label} rejected: {'; '.join(bad)}")
        p = self.path(key)
        self.root.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, p)
        self.index[key] = {"bytes": p.stat().st_size, "frames": frames, "last_used": time.time(), "label": label}
        return p

    def prune(self, keep: set[str]) -> list[str]:
        """Drop least-recently-used clips until the store fits max_bytes. Clips in `keep` (the current run) are never
        removed, and only files named <sha256>.mp4 inside the cache directory are ever deleted."""
        removed: list[str] = []
        if not self.root.is_dir():
            return removed
        for t in self.root.glob("*.part.mp4"):    # leftovers of an interrupted render
            t.unlink(missing_ok=True)
        clips = {p.stem: p for p in self.root.glob("*.mp4") if _KEY_RE.fullmatch(p.stem)}
        for k in list(self.index):
            if k not in clips:
                self.index.pop(k)
        total = sum(p.stat().st_size for p in clips.values())
        order = sorted((k for k in clips if k not in keep), key=lambda k: self.index.get(k, {}).get("last_used", 0))
        for k in order:
            if total <= self.max_bytes:
                break
            total -= clips[k].stat().st_size
            clips[k].unlink()
            self.index.pop(k, None)
            removed.append(k)
        self.save()
        return removed


# ------------------------------------------------------------------ join
def join_clips(clips: list[Path], dst: Path, frames: int) -> None:
    """Stream-copy concat (exact, no re-encode). Fails unless the result has exactly `frames` frames."""
    if not clips:
        raise SceneCacheError("nothing to join")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".joining.mp4")
    lst = dst.with_name(dst.stem + ".concat.txt")
    lst.write_text("".join("file '" + str(Path(c).resolve()).replace("'", "'\\''") + "'\n" for c in clips))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0:v:0",
                        "-c", "copy", "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    if r.returncode:
        tmp.unlink(missing_ok=True)
        raise SceneCacheError(f"join failed: {r.stderr[-300:]}")
    v = probe_video(tmp)
    if v["frames"] != frames or abs(v["duration"] - frames / FPS) > 0.5 / FPS:
        tmp.unlink(missing_ok=True)
        raise SceneCacheError(f"joined video has {v['frames']} frames / {v['duration']:.3f}s, expected {frames} / {frames / FPS:.3f}s")
    os.replace(tmp, dst)


# ------------------------------------------------------------------ one output
RenderSegments = Callable[..., None]   # (props_path, public, [{"from", "to" (inclusive), "out"}], *, scale) -> None


def plan_output(props: dict, public: Path, scale: float, renderer: str | None = None) -> tuple[list[dict], list[dict]]:
    plan = frame_plan(props["scenes"], style=props.get("style"))
    segs = segments(plan, int(props["durationInFrames"]))
    stamp = renderer or renderer_stamp()
    for s in segs:
        s["key"] = segment_key(props, plan, s, public=public, scale=scale, renderer=stamp)
    return plan, segs


def render_output(props_path: Path, public: Path, dst: Path, cache: SceneCache, render_segments: RenderSegments, *,
                  scale: float = 1.0, force_scenes: set[str] | frozenset = frozenset(), renderer: str | None = None,
                  log: Callable = print, label: str = "") -> dict:
    """Render one output through the cache and join it to dst. Segments showing any scene in force_scenes are rendered
    again even when cached. Returns {segments, rendered: [names], reused, keys}."""
    props = json.loads(Path(props_path).read_text(encoding="utf-8"))
    w, h = int(props["width"] * scale), int(props["height"] * scale)
    plan, segs = plan_output(props, public, scale, renderer)
    ids = {p["id"] for p in plan}
    unknown = set(force_scenes) - ids
    if unknown:
        raise SceneCacheError(f"{label}: unknown scene id(s) {sorted(unknown)}; known: {sorted(ids)}")
    clips: dict[int, Path] = {}
    todo = []
    for i, s in enumerate(segs):
        forced = any(plan[j]["id"] in force_scenes for j in s["visible"])
        hit = None if forced else cache.get(s["key"], s["to"] - s["from"], w, h)
        if hit:
            clips[i] = hit
        else:
            todo.append(i)
    if todo:
        cache.root.mkdir(parents=True, exist_ok=True)
        jobs = [{"from": segs[i]["from"], "to": segs[i]["to"] - 1, "out": str(cache.root / f"{segs[i]['key']}.part.mp4")} for i in todo]
        render_segments(Path(props_path), public, jobs, scale=scale)
        for i, j in zip(todo, jobs):
            s = segs[i]
            clips[i] = cache.put(s["key"], Path(j["out"]), s["to"] - s["from"], w, h, f"{label}/{s['name']}")
    join_clips([clips[i] for i in range(len(segs))], dst, int(props["durationInFrames"]))
    cache.save()
    rendered = [segs[i]["name"] for i in todo]
    log(f"  {label}: {len(segs)} segments, {len(todo)} rendered" + (f" ({', '.join(rendered)})" if rendered else "")
        + f", {len(segs) - len(todo)} from cache")
    return {"segments": len(segs), "rendered": rendered, "reused": len(segs) - len(todo), "keys": [s["key"] for s in segs]}
