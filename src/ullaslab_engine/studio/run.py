"""`studio run <queue-item> [--preview]`: resumable stages timings -> broll -> assemble -> render -> mix -> package.

Each stage records a checkpoint (hash of its input files plus mode) in <item>/work/studio.json; a rerun skips a stage
whose checkpoint matches and whose outputs exist. Finals are versioned (long.mp4, long.v2.mp4, ...) and never overwritten.
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
from .timings import UNSPACED, CoverageError, time_output, transcribe_words

STAGES = ["timings", "broll", "assemble", "render", "mix", "package"]
REMOTION = ROOT / "remotion"


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


class Studio:
    def __init__(self, item: Path, *, preview: bool = False, lang: str = "en", asr_backend: str = "auto", force: bool = False,
                 asr: Callable | None = None, render: Callable | None = None, fetch: Callable | None = None, log: Callable = print):
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

    # ---- checkpoints
    def _done(self, name: str, key: str, outputs: list[Path]) -> bool:
        rec = self.state["stages"].get(f"{name}:{self.mode if name not in ('timings', 'broll') else 'all'}")
        return bool(rec and rec["key"] == key and all(o.exists() for o in outputs) and not self.force)

    def _mark(self, name: str, key: str, **extra) -> None:
        k = f"{name}:{self.mode if name not in ('timings', 'broll') else 'all'}"
        self.state["stages"][k] = {"key": key, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1))

    def _stage(self, name: str, key: str, outputs: list[Path], fn: Callable) -> None:
        if self._done(name, key, outputs):
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

        def go():
            t0 = time.time()
            for o, v in zip(doc["outputs"], outs):
                props = self.wmode / f"props.{o['output']}.json"
                self.render(props, pub, v, scale=0.5 if self.preview else 1.0)
            if not self.preview:
                self.render_thumb(doc, pub, thumb)
            return {"render_s": round(time.time() - t0, 1)}
        needed = outs + ([] if self.preview else [thumb])
        self._stage("render", sha([self.wmode / f"props.{o['output']}.json" for o in doc["outputs"]], self.mode), needed, go)

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
        p.write_text(json.dumps(tp, ensure_ascii=False))
        self.render(p, pub, dst, comp="StudioThumb", frame=45)

    def s_mix(self) -> None:
        doc = self.timed()
        outs = [self.wmode / f"final.{o['output']}.mp4" for o in doc["outputs"]]
        meta_p = self.wmode / "audio.json"

        def go():
            lib = A.make_sfx_library(self.work / "sfx_lib")
            ledger = A.load_music_ledger()
            meta = {}
            for o, final in zip(doc["outputs"], outs):
                n = o["output"]
                props = json.loads((self.wmode / f"props.{n}.json").read_text())
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
                    src = A.generate_pad(st / "pad_source.wav", min(total, 60.0))
                A.run(A.music_stem_cmd(src, total, st / "music.wav"), "music stem")
                A.run(A.mix_cmd(st / "narration.wav", st / "music.wav", st / "sfx.wav", st / "mix.wav"), "ducked mix")
                pre = A.loudnorm_two_pass(st / "mix.wav", st / "master.wav")
                m = A.measure(st / "master.wav")
                if abs(m["lufs"] - A.TARGET_LUFS) > 1.0 or m["true_peak_dbtp"] > A.TP_LIMIT:
                    raise StudioError(f"{n}: mix out of spec {m} (target {A.TARGET_LUFS} LUFS, TP <= {A.TP_LIMIT})")
                A.run(A.mux_cmd(self.wmode / f"video.{n}.mp4", st / "master.wav", final), "mux")
                w, h = props["width"], props["height"]
                if self.preview:
                    w, h = w // 2, h // 2
                bad = check_spec(final, w, h)
                if bad:
                    raise StudioError(f"{n}: spec check failed: {bad}")
                meta[n] = {"music": track, "sfx": sorted({e[0] for e in events}), "measure": m, "pre_norm_lufs": pre.get("input_i")}
                self.log(f"  {n}: {m['lufs']} LUFS, {m['true_peak_dbtp']} dBTP, music={track['id']}, sfx={len(events)}")
            meta_p.write_text(json.dumps(meta, indent=1))
        self._stage("mix", sha([self.wmode / f"video.{o['output']}.mp4" for o in doc["outputs"]], self.mode), outs + [meta_p], go)

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
        marker = self.state["stages"].get("package:final")
        if marker and marker["key"] == key and not self.force and all((self.item / f).exists() for f in marker.get("files", [])):
            self.log("[package] skipped (checkpoint)")
            return [self.item / f for f in marker["files"]]
        self.log("[package] running")
        for o in doc["outputs"]:
            n = o["output"]
            made.append(K.publish_file(self.wmode / f"final.{n}.mp4", self.item, n, ".mp4"))
            cues = json.loads((self.wmode / f"props.{n}.json").read_text())["captions"]
            srt = self.wmode / f"captions.{n}.srt"
            srt.write_text(cues_to_srt(cues), encoding="utf-8")
            made.append(K.publish_file(srt, self.item, f"captions.{n}", ".srt"))
        made.append(K.publish_file(self.wmode / "thumb.png", self.item, "thumb", ".png"))
        assets = json.loads((self.item / "assets.json").read_text())["assets"] if (self.item / "assets.json").is_file() else []
        meta = json.loads((self.item / "meta.json").read_text()) if (self.item / "meta.json").is_file() else {}
        K.merge_assets_md(self.item, audio)
        usage = {"render_s": self.state["stages"].get("render:final", {}).get("render_s", 0),
                 "asr": next(iter(self.state["stages"].get("timings:all", {}).get("timing", {}).values()), {}).get("asr", "whisper"),
                 "broll": self.state["stages"].get("broll:all", {})}
        (self.item / "cost.md").write_text(K.cost_md(self.item, usage), encoding="utf-8")
        (self.item / "publish.md").write_text(K.publishing_pack(self.item, doc, meta, assets, audio), encoding="utf-8")
        self._mark("package", key, files=[p.name for p in made])
        self.ran.append("package")
        self.log("[package] " + ", ".join(p.name for p in made))
        return made

    def run(self, until: str = "package") -> list[Path]:
        made: list[Path] = []
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


def cmd_studio_run(a) -> int:
    s = Studio(Path(a.item), preview=a.preview, lang=a.lang, asr_backend=a.asr, force=a.force)
    try:
        made = s.run(a.until)
    except (StudioError, AssembleError, CoverageError, A.AudioError) as e:
        print(f"studio: {type(e).__name__}: {e}")
        return 1
    for w in dict.fromkeys(s.warnings):
        print("warning:", w)
    print("done:", ", ".join(p.name for p in made) or a.until)
    return 0
