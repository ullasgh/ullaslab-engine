"""`studio run <queue-item> [--preview]`: resumable stages timings -> broll -> assemble -> render -> mix -> package.

Each stage records a checkpoint (hash of its input files plus mode) in <item>/work/studio.json; a rerun skips a stage
whose checkpoint matches and whose outputs exist. Finals are versioned (long.mp4, long.v2.mp4, ...) and never overwritten;
only an output whose final changed (or that was named with --scene) gets a new version.
The render stage goes through the per-scene cache (studio/scenecache.py): each scene's frame span is rendered once and
reused until something that can change its pixels changes; `--scene s03` re-renders the spans showing s03 and rejoins.
Item contract (inputs): scenes.json, voice.<output>.wav or voice.wav, optional meta.json, chart_specs.json (resolved),
visual_data.json, assets.json + footage/ (written by the broll stage)."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import soundfile as sf

from ..config import ROOT
from . import FPS, audio as A, pack as K
from .assemble import ASPECT_SIZE, AssembleError, build_props, load_assets
from .captions import cues_to_srt
from .qc import QCError
from . import scenecache as SC
from .timings import UNSPACED, CoverageError, time_output, transcribe_words

STAGES = ["timings", "broll", "assemble", "render", "mix", "package", "qc"]
REMOTION = ROOT / "remotion"
OWNER_MARKER = "APPR" + "OVED"   # the owner's local approval file: read-only here, never created or changed by the engine


class StudioError(RuntimeError):
    pass


def sha(paths: list[Path], extra: str = "") -> str:
    h = hashlib.sha256(extra.encode())
    for p in sorted(paths):
        h.update(p.name.encode())
        if p.is_file():
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:20]


def node_render(props: Path, public: Path, out: Path, *, comp: str = "StudioVideo", scale: float = 1.0, frame: int | None = None) -> None:
    cmd = ["node", str(REMOTION / "studio_render.mjs"), "--props", str(props), "--public", str(public), "--out", str(out), "--id", comp]
    cmd += ["--scale", str(scale)] if frame is None else ["--frame", str(frame)]
    r = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True)
    if r.returncode:
        raise StudioError(f"remotion render failed: {(r.stderr or r.stdout)[-600:]}")


def node_render_segments(props: Path, public: Path, jobs: list[dict], *, scale: float = 1.0) -> None:
    """Render frame spans of one StudioVideo in a single bundle (studio_render.mjs --segments)."""
    seg = props.with_name(props.stem + ".segments.json")
    seg.write_text(json.dumps(jobs))
    cmd = ["node", str(REMOTION / "studio_render.mjs"), "--props", str(props), "--public", str(public), "--segments", str(seg),
           "--scale", str(scale)]
    r = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True)
    if r.returncode:
        raise StudioError(f"remotion segment render failed: {(r.stderr or r.stdout)[-600:]}")


def ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True)
    if r.returncode:
        raise StudioError(f"ffprobe failed for {path.name}")
    return json.loads(r.stdout)


def check_spec(path: Path, w: int, h: int) -> list[str]:
    """Spec check: H.264 High, yuv420p, WxH, 30 fps, AAC 48 kHz. Returns the list of problems."""
    d = ffprobe(path)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    bad = []
    if v["codec_name"] != "h264" or v.get("profile") != "High":
        bad.append(f"video {v['codec_name']}/{v.get('profile')}")
    if v["pix_fmt"] != "yuv420p":
        bad.append(f"pix_fmt {v['pix_fmt']}")
    if (v["width"], v["height"]) != (w, h):
        bad.append(f"size {v['width']}x{v['height']}")
    if v["r_frame_rate"] != f"{FPS}/1":
        bad.append(f"fps {v['r_frame_rate']}")
    if not a or a["codec_name"] != "aac" or int(a["sample_rate"]) != 48000:
        bad.append("audio not AAC 48 kHz")
    return bad


AV_SYNC_TOL_S = 0.05


def av_sync_problems(path: Path, frames: int) -> list[str]:
    """After the mux: the video has exactly `frames` frames and the audio ends with it (within AV_SYNC_TOL_S)."""
    d = ffprobe(path)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    bad = []
    n = int(v.get("nb_frames") or 0)
    if n != frames:
        bad.append(f"video has {n} frames, expected {frames}")
    if a is None:
        return bad + ["no audio stream"]
    vd, ad = float(v.get("duration") or 0), float(a.get("duration") or 0)
    if abs(vd - ad) > AV_SYNC_TOL_S:
        bad.append(f"audio {ad:.3f}s vs video {vd:.3f}s (tolerance {AV_SYNC_TOL_S}s)")
    return bad


class Studio:
    def __init__(self, item: Path, *, preview: bool = False, lang: str = "en", asr_backend: str = "auto", force: bool = False,
                 asr: Callable | None = None, render: Callable | None = None, fetch: Callable | None = None, log: Callable = print,
                 scene_cache: bool = True, scenes: list[str] | None = None, output: str | None = None,
                 render_segments: Callable | None = None, cache_max_bytes: int | None = None):
        self.item = Path(item).resolve()
        self.preview, self.lang, self.backend, self.force = preview, lang, asr_backend, force
        self.mode = "preview" if preview else "final"
        self.work = self.item / "work"
        self.wmode = self.work / self.mode
        self.asr = asr or (lambda p, lang: transcribe_words(p, lang, self.backend))
        self.render = render or node_render
        self.fetch = fetch
        self.log = log
        self.state_path = self.work / "studio.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.is_file() else {"stages": {}}
        self.warnings: list[str] = []
        self.ran: list[str] = []
        # Per-scene cache: on with the real renderer, or when a segment renderer is injected (tests). A custom whole-video
        # `render` without `render_segments` keeps the old single render.
        self.use_cache = scene_cache and (render is None or render_segments is not None)
        self.render_segments = render_segments or node_render_segments
        self.cache = SC.SceneCache(self.work / "scene_cache", cache_max_bytes)
        self.force_scenes = [s for x in (scenes or []) for s in str(x).split(",") if s.strip()]
        self.force_scenes = [s.strip() for s in self.force_scenes]
        self.only_output = output
        if self.force_scenes and not self.use_cache:
            raise StudioError("--scene needs the per-scene cache (drop --no-scene-cache)")
        if output and not self.force_scenes:
            raise StudioError("--output selects the output for --scene; give --scene too")

    # ---- checkpoints
    def _done(self, name: str, key: str, outputs: list[Path]) -> bool:
        rec = self.state["stages"].get(f"{name}:{self.mode if name not in ('timings', 'broll') else 'all'}")
        return bool(rec and rec["key"] == key and all(o.exists() for o in outputs) and not self.force)

    def _mark(self, name: str, key: str, **extra) -> None:
        k = f"{name}:{self.mode if name not in ('timings', 'broll') else 'all'}"
        self.state["stages"][k] = {"key": key, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1))

    def _stage(self, name: str, key: str, outputs: list[Path], fn: Callable, *, always: bool = False) -> None:
        if not always and self._done(name, key, outputs):
            self.log(f"[{name}] skipped (checkpoint)")
            return
        self.log(f"[{name}] running")
        self.wmode.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        extra = fn() or {}
        self._mark(name, key, seconds=round(time.time() - t0, 1), **extra)
        self.ran.append(name)

    # ---- inputs
    def scenes_doc(self) -> dict:
        p = self.item / "scenes.json"
        if not p.is_file():
            raise StudioError(f"{p} not found (run the director first)")
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("schema_version") != 1 or not d.get("outputs"):
            raise StudioError("scenes.json: expected schema_version 1 with outputs[]")
        return d

    def voice_for(self, out: str) -> Path:
        for n in (f"voice.{out}.wav", "voice.wav"):
            if (self.item / n).is_file():
                return self.item / n
        raise StudioError(f"no voice track for '{out}' (voice.{out}.wav or voice.wav)")

    def timed(self) -> dict:
        return json.loads((self.work / "scenes.timed.json").read_text(encoding="utf-8"))

    def forced(self, doc: dict) -> dict[str, set[str]]:
        """{output: scene ids} for --scene. An id that is in none of the selected outputs is an error (nothing runs)."""
        if not self.force_scenes:
            return {}
        outs = [o for o in doc["outputs"] if not self.only_output or o["output"] == self.only_output]
        if self.only_output and not outs:
            raise StudioError(f"--output {self.only_output!r}: no such output (have {[o['output'] for o in doc['outputs']]})")
        got: dict[str, set[str]] = {}
        for o in outs:
            ids = {sc["id"] for sc in o["scenes"]}
            hit = ids & set(self.force_scenes)
            if hit:
                got[o["output"]] = hit
        missing = set(self.force_scenes) - {s for v in got.values() for s in v}
        if missing:
            where = f"output {self.only_output!r}" if self.only_output else "any output"
            raise StudioError(f"unknown scene id(s) {sorted(missing)} in {where} of scenes.json")
        return got

    # ---- stages
    def cached_asr(self, voice: Path) -> tuple[list, str]:
        """ASR once per distinct voice file (outputs sharing a voice.wav reuse it)."""
        h = hashlib.sha256(voice.read_bytes()).hexdigest()[:16]
        c = self.work / "asr" / f"{h}.{self.lang}.{self.backend}.json"
        if c.is_file():
            d = json.loads(c.read_text())
            return [tuple(w) for w in d["words"]], d["backend"]
        words, used = self.asr(voice, self.lang)
        c.parent.mkdir(parents=True, exist_ok=True)
        c.write_text(json.dumps({"words": words, "backend": used}))
        return words, used

    def s_timings(self) -> None:
        doc = self.scenes_doc()
        if self.lang in UNSPACED:
            raise StudioError(f"language '{self.lang}' is written without spaces: studio word alignment does not support it yet (known limit, docs/studio.md)")
        voices = [self.voice_for(o["output"]) for o in doc["outputs"]]
        out = self.work / "scenes.timed.json"

        def go():
            stats = {}
            for o, v in zip(doc["outputs"], voices):
                words, used = self.cached_asr(v)
                (self.work / f"words.{o['output']}.json").write_text(json.dumps(words))
                dur = sf.info(str(v)).duration
                stats[o["output"]] = {**time_output(o["scenes"], words, dur, label=o["output"], lang=self.lang), "asr": used}
                self.log(f"  {o['output']}: coverage {stats[o['output']]['coverage']:.1%} via {used}, {stats[o['output']]['total_s']}s")
            out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
            return {"timing": stats}
        self._stage("timings", sha([self.item / "scenes.json", *voices], f"{self.lang}{self.backend}"), [out], go)

    def s_broll(self) -> None:
        doc = self.timed()
        need = [(o["output"], sc["id"]) for o in doc["outputs"] for sc in o["scenes"] if sc["type"] == "footage"]
        out = self.item / "assets.json"

        def go():
            if not need:
                return {"footage_scenes": 0}
            have = load_assets(self.item)
            if all(k in have and (self.item / have[k]["filename"]).is_file() for k in need):
                self.log("  footage already in the asset ledger, no fetch")
                return {"footage_scenes": len(need), "fetched": 0}
            fetch = self.fetch
            if fetch is None:
                from ..broll.run import run_fetch
                fetch = run_fetch
            r = fetch(self.work / "scenes.timed.json", self.item, episode=self.item.name)
            miss = [x for x in r["report"] if x["status"] != "ok"]
            if miss and not self.preview:
                raise StudioError(f"broll: no candidate for {[(m['output'], m['scene']) for m in miss]}; set PIXABAY_API_KEY, import clips "
                                  f"into footage/inbox, or rerun with --preview to use placeholders")
            if miss:
                self.warnings.append(f"broll: {len(miss)} scenes without footage (preview placeholders)")
            h = r["http"]
            return {"footage_scenes": len(need), "fetched": len(r["entries"]), "requests_used": h.used, "cache_hits": h.cache_hits}
        key_files = [self.work / "scenes.timed.json"] + ([out] if out.is_file() else [])
        self._stage("broll", sha(key_files[:1]), [out] if need else [], go)

    def s_assemble(self) -> None:
        doc = self.timed()
        pub = self.wmode / "public"
        inputs = [self.work / "scenes.timed.json", self.item / "assets.json", self.item / "chart_specs.json",
                  self.item / "charts.resolved.json", self.item / "visual_data.json"]
        outs = [self.wmode / f"props.{o['output']}.json" for o in doc["outputs"]]

        def go():
            pub.mkdir(parents=True, exist_ok=True)
            for o, p in zip(doc["outputs"], outs):
                props, warns = build_props(self.item, doc, o, pub, lang=self.lang, allow_placeholder=self.preview)
                self.warnings += warns
                p.write_text(json.dumps(props, ensure_ascii=False))
            return {"warnings": self.warnings}
        self._stage("assemble", sha(inputs, self.mode), outs, go)

    def s_render(self) -> None:
        doc = self.timed()
        pub = self.wmode / "public"
        outs = [self.wmode / f"video.{o['output']}.mp4" for o in doc["outputs"]]
        thumb = self.wmode / "thumb.png"

        forced = self.forced(doc)
        scale = 0.5 if self.preview else 1.0

        def go():
            t0 = time.time()
            stats, keep = {}, set()
            for o, v in zip(doc["outputs"], outs):
                n = o["output"]
                props = self.wmode / f"props.{n}.json"
                if self.use_cache:
                    st = SC.render_output(props, pub, v, self.cache, self.render_segments, scale=scale, force_scenes=forced.get(n, set()),
                                          log=self.log, label=n)
                    keep |= set(st.pop("keys"))
                    stats[n] = st
                else:
                    self.render(props, pub, v, scale=scale)
            if self.use_cache:
                gone = self.cache.prune(keep)
                if gone:
                    self.log(f"  scene cache: pruned {len(gone)} old clip(s) (limit {self.cache.max_bytes // (1024 * 1024)} MB)")
            if not self.preview:
                self.render_thumb(doc, pub, thumb)
            return {"render_s": round(time.time() - t0, 1), "scene_cache": stats if self.use_cache else "off"}
        needed = outs + ([] if self.preview else [thumb])
        key = sha([self.wmode / f"props.{o['output']}.json" for o in doc["outputs"]], f"{self.mode}|cache={self.use_cache}")
        self._stage("render", key, needed, go, always=bool(forced))

    def render_thumb(self, doc: dict, pub: Path, dst: Path) -> None:
        o = next((x for x in doc["outputs"] if x["aspect"] == "16:9"), doc["outputs"][0])
        props = json.loads((self.wmode / f"props.{o['output']}.json").read_text())
        hook = dict(props["scenes"][0])
        hook["narration"] = {"text": hook["narration"]["text"], "start_s": 0.0, "end_s": 4.0}
        hook["transition"] = "cut"
        head = (hook.get("on_screen_text") or hook["narration"]["text"]).replace("|", " ").replace("*", "").strip()
        if len(head) > 70:
            head = head[:67].rsplit(" ", 1)[0] + "..."
        hook["on_screen_text"] = None     # the thumbnail carries the headline; the art keeps no duplicate text
        tp = {"orientation": "horizontal", "scenes": [hook], "refs": props["refs"], "lang": props["lang"], "numberLocale": props["numberLocale"],
              "headline": head, "art": hook["type"] != "kinetic"}
        p = self.wmode / "props.thumb.json"
        blob = json.dumps(tp, ensure_ascii=False)
        p.write_text(blob)
        kp = self.wmode / "thumb.key"
        key = hashlib.sha256((blob + "|" + (SC.renderer_stamp() if self.render is node_render else "custom")).encode()).hexdigest()
        if not self.force and dst.is_file() and kp.is_file() and kp.read_text() == key:
            self.log("  thumbnail unchanged, kept")
            return
        self.render(p, pub, dst, comp="StudioThumb", frame=45)
        kp.write_text(key)

    def s_mix(self) -> None:
        doc = self.timed()
        outs = [self.wmode / f"final.{o['output']}.mp4" for o in doc["outputs"]]
        meta_p = self.wmode / "audio.json"
        forced = self.forced(doc)

        def go():
            try:
                prev = json.loads(meta_p.read_text()) if meta_p.is_file() else {}
            except ValueError:
                prev = {}
            lib = A.make_sfx_library(self.work / "sfx_lib")
            ledger = A.load_music_ledger()
            fetch = A.fetch_missing_tracks(ledger)
            if fetch["fetched"]:
                self.log(f"  music: fetched from private R2: {', '.join(fetch['fetched'])}")
            for tid, why in fetch["failed"].items():
                self.log(f"  WARNING: licensed music '{tid}' could not be fetched from R2 ({why})")
            meta = {}
            for o, final in zip(doc["outputs"], outs):
                n = o["output"]
                props = json.loads((self.wmode / f"props.{n}.json").read_text())
                vsha = sha([self.wmode / f"video.{n}.mp4"], "video")
                asha = sha([self.voice_for(n)], "voice")
                p = prev.get(n) or {}
                if (not self.force and n not in forced and final.is_file() and p.get("video_sha") == vsha and p.get("voice_sha") == asha
                        and p.get("mix_cfg") == A.mix_cfg()):
                    meta[n] = p          # this output's picture and voice are unchanged: keep its mix
                    self.log(f"  {n}: unchanged, mix kept")
                    continue
                total = props["durationInFrames"] / FPS
                st = self.wmode / "stems" / n
                st.mkdir(parents=True, exist_ok=True)
                A.run(A.narration_stem_cmd(self.voice_for(n), total, st / "narration.wav"), "narration stem")
                events = A.sfx_events(o["scenes"])
                A.run(A.sfx_stem_cmd(events, lib, total, st / "sfx.wav"), "sfx stem")
                track = A.pick_track(ledger, mood=o["scenes"][0].get("palette"))
                if track:
                    src = A.MUSIC_DIR / track["file"]
                else:
                    track = A.generated_track()
                    if ledger:
                        track["fallback"] = {"reason": "ledger tracks exist but none is available locally or from R2", "fetch_failed": fetch["failed"]}
                        self.log(f"  WARNING: {n} is using the generated CC0 pad although {len(ledger)} licensed track(s) are in the ledger "
                                 f"(R2 fetch failed: {fetch['failed'] or 'not attempted'}). Set R2_* env or run `wrangler login`.")
                    src = A.generate_pad(st / "pad_source.wav", min(total, 60.0))
                A.run(A.music_stem_cmd(src, total, st / "music.wav"), "music stem")
                duck = A.apply_duck(st / "narration.wav", st / "music.wav", st / "music_ducked.wav")
                A.run(A.mix_cmd(st / "narration.wav", st / "music_ducked.wav", st / "sfx.wav", st / "mix.wav"), "ducked mix")
                pre = A.loudnorm_two_pass(st / "mix.wav", st / "master.wav")
                m = A.measure(st / "master.wav")
                if abs(m["lufs"] - A.TARGET_LUFS) > 1.0 or m["true_peak_dbtp"] > A.TP_LIMIT:
                    raise StudioError(f"{n}: mix out of spec {m} (target {A.TARGET_LUFS} LUFS, TP <= {A.TP_LIMIT})")
                A.run(A.mux_cmd(self.wmode / f"video.{n}.mp4", st / "master.wav", final, total), "mux")
                w, h = props["width"], props["height"]
                if self.preview:
                    w, h = w // 2, h // 2
                bad = check_spec(final, w, h) + av_sync_problems(final, props["durationInFrames"])
                if bad:
                    raise StudioError(f"{n}: spec / A/V sync check failed: {bad}")
                meta[n] = {"music": track, "sfx": sorted({e[0] for e in events}), "measure": m, "duck": duck, "pre_norm_lufs": pre.get("input_i"),
                           "video_sha": vsha, "voice_sha": asha, "mix_cfg": A.mix_cfg()}
                self.log(f"  {n}: {m['lufs']} LUFS, {m['true_peak_dbtp']} dBTP, music={track['id']}, sfx={len(events)}")
            meta_p.write_text(json.dumps(meta, indent=1))
        self._stage("mix", sha([self.wmode / f"video.{o['output']}.mp4" for o in doc["outputs"]], self.mode), outs + [meta_p], go,
                    always=bool(forced))

    def s_package(self) -> list[Path]:
        doc = self.timed()
        made: list[Path] = []
        audio = json.loads((self.wmode / "audio.json").read_text())
        if self.preview:
            pd = self.item / "preview"
            pd.mkdir(exist_ok=True)
            for o in doc["outputs"]:
                made.append(K.publish_file(self.wmode / f"final.{o['output']}.mp4", pd, o["output"], ".mp4"))
            self.log("[package] preview files: " + ", ".join(str(p.relative_to(self.item)) for p in made))
            return made
        key = sha([self.wmode / f"final.{o['output']}.mp4" for o in doc["outputs"]], "pkg")
        marker = self.state["stages"].get("package:final") or {}
        forced = self.forced(doc)
        cur = {o["output"]: sha([self.wmode / f"final.{o['output']}.mp4"], "final") for o in doc["outputs"]}
        thumb_sha = sha([self.wmode / "thumb.png"], "thumb")
        by_out = marker.get("by_output") or {}
        exists = lambda names: bool(names) and all((self.item / f).exists() for f in names)

        def keep(n: str) -> bool:      # this output's published files still match its current final
            if self.force or n in forced:
                return False
            if "outputs" not in marker:   # checkpoint from before per-output packaging: all or nothing, as before
                return marker.get("key") == key and exists(by_out.get(n) or marker.get("files", []))
            return marker["outputs"].get(n) == cur[n] and exists(by_out.get(n, []))
        kept = {o["output"]: keep(o["output"]) for o in doc["outputs"]}
        thumb_keep = (not self.force and marker.get("thumb") == thumb_sha and exists([marker.get("thumb_file", "")])) or \
                     ("outputs" not in marker and marker.get("key") == key and not self.force and exists(marker.get("files", [])))
        if all(kept.values()) and thumb_keep and marker.get("files") and exists(marker["files"]):
            self.log("[package] skipped (checkpoint)")
            return [self.item / f for f in marker["files"]]
        self.log("[package] running")
        new_by_out: dict[str, list[str]] = {}
        for o in doc["outputs"]:
            n = o["output"]
            if kept[n] and by_out.get(n):
                new_by_out[n] = by_out[n]
                made += [self.item / f for f in by_out[n]]
                continue
            files = [K.publish_file(self.wmode / f"final.{n}.mp4", self.item, n, ".mp4")]
            cues = json.loads((self.wmode / f"props.{n}.json").read_text())["captions"]
            srt = self.wmode / f"captions.{n}.srt"
            srt.write_text(cues_to_srt(cues), encoding="utf-8")
            files.append(K.publish_file(srt, self.item, f"captions.{n}", ".srt"))
            new_by_out[n] = [p.name for p in files]
            made += files
        if thumb_keep and marker.get("thumb_file"):
            thumb_file = self.item / marker["thumb_file"]
        else:
            thumb_file = K.publish_file(self.wmode / "thumb.png", self.item, "thumb", ".png")
        made.append(thumb_file)
        assets = json.loads((self.item / "assets.json").read_text())["assets"] if (self.item / "assets.json").is_file() else []
        meta = json.loads((self.item / "meta.json").read_text()) if (self.item / "meta.json").is_file() else {}
        K.merge_assets_md(self.item, audio)
        usage = {"render_s": self.state["stages"].get("render:final", {}).get("render_s", 0),
                 "asr": next(iter(self.state["stages"].get("timings:all", {}).get("timing", {}).values()), {}).get("asr", "whisper"),
                 "broll": self.state["stages"].get("broll:all", {})}
        (self.item / "cost.md").write_text(K.cost_md(self.item, usage), encoding="utf-8")
        (self.item / "publish.md").write_text(K.publishing_pack(self.item, doc, meta, assets, audio), encoding="utf-8")
        self._mark("package", key, files=[p.name for p in made], outputs=cur, by_output=new_by_out, thumb=thumb_sha, thumb_file=thumb_file.name)
        self.ran.append("package")
        new = [n for n in new_by_out if not kept[n]]
        self.log("[package] " + ", ".join(p.name for p in made) + (f" (new version: {', '.join(new)})" if new else ""))
        if new and (self.item / OWNER_MARKER).exists():
            msg = (f"this item has the owner's local approval file, but {', '.join(new)} changed after it: the approval covers the "
                   f"files that were reviewed, so the owner must review and approve again (the signed studio approval is voided "
                   f"automatically once the new files are uploaded, because its content hash changes)")
            self.warnings.append(msg)
            self.log("  WARNING: " + msg)
        return made

    def run(self, until: str = "package") -> list[Path]:
        made: list[Path] = []
        self.forced(self.scenes_doc())        # an unknown --scene id fails before any stage runs
        steps = [("timings", self.s_timings), ("broll", self.s_broll), ("assemble", self.s_assemble), ("render", self.s_render),
                 ("mix", self.s_mix), ("package", None)]
        for name, fn in steps:
            if name == "package":
                made = self.s_package()
            else:
                fn()
            if name == until:
                break
        return made

    def s_qc(self):
        """Last stage: automated QC of the packaged files (not checkpointed; cheap and always current). Writes qc.md / qc.json."""
        from .qc import qc_item
        rep = qc_item(self.item, preview=self.preview)
        self.log(f"[qc] {rep.verdict()}: " + ", ".join(f"{o}={rep.verdict(o)}" for o in rep.outputs))
        return rep


def cmd_studio_run(a) -> int:
    try:
        s = Studio(Path(a.item), preview=a.preview, lang=a.lang, asr_backend=a.asr, force=a.force,
                   scene_cache=not getattr(a, "no_scene_cache", False), scenes=getattr(a, "scene", None) or None,
                   output=getattr(a, "output", None))
    except StudioError as e:
        print(f"studio: {type(e).__name__}: {e}")
        return 1
    try:
        made = s.run("package" if a.until == "qc" else a.until)
        rep = s.s_qc() if a.until == "qc" else None
    except (StudioError, AssembleError, CoverageError, A.AudioError, QCError, SC.SceneCacheError) as e:
        print(f"studio: {type(e).__name__}: {e}")
        return 1
    for w in dict.fromkeys(s.warnings):
        print("warning:", w)
    print("done:", ", ".join(p.name for p in made) or a.until)
    if rep is not None:
        print(f"qc: {rep.verdict()} (see qc.md)")
        return 1 if rep.verdict() == "FAIL" else 0
    return 0
