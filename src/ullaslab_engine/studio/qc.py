"""Automated QC for a studio queue item: `studio qc <item>` and the last stage of `studio run`.

Writes qc.md and qc.json into the queue folder (PASS / WARN / FAIL per check, one verdict per output, one overall verdict)
and contact_sheet.<output>.png per output. Everything is local ffmpeg / ffprobe / numpy; no network, no cost.

Checks per output
  spec       ffprobe size, 30 fps, H.264 yuv420p, AAC 48 kHz, duration vs voice (+-0.5 s), faststart (moov before mdat)
  visual     blackdetect (>=0.5 s), freezedetect (>=2 s unless the scene is a deliberate `hold`), repeated clips
             (asset sha256, then perceptual hash of shots)
  audio      silencedetect on the narration (>1.5 s), loudness (-14 +-1 LUFS, true peak <= -1 dBTP), clipping
  captions   layout limits, no text-like content outside the safe box in sampled frames, SRT cues vs word timings (drift > 150 ms)
Checks per item
  data       chart data_ref resolves, chart hash vs ledger, number tags, footage ledger entries, deny-listed names
  platform   disclaimer, synthetic-voice flag, AI label recommendation
The default thresholds live in DEFAULTS and can be overridden by a `QC:` block in config/quality.yaml."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from ..config import ROOT, quality
from ..qa import chart_hash
from . import FPS
from .assemble import AssembleError, load_assets, load_chart_specs, to_kit_chart
from .pack import DISCLAIMER

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
RANK = {PASS: 0, WARN: 1, FAIL: 2}
TAGS = {"LIVE", "RECENT", "LAGGED", "EXPECTATION", "INFERRED"}
ASPECT_SIZE = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
DENY = [("Schwab", r"schwab"), ("FYERS", r"fyers"), ("NSE feed", r"\bnse\b[\s_-]*(?:data[\s_-]*)?feeds?\b"),
        ("Atlas", r"(?<!world)(?<!world )(?<!world-)\batlas\b(?!\s+of\b)"), ("yfinance", r"yfinance"), ("investing.com", r"investing\.com")]

DEFAULTS = {
    "duration_tol_s": 0.5, "black_min_s": 0.5, "black_edge_fade_max_s": 1.0, "freeze_min_s": 2.0, "silence_min_s": 1.5, "silence_db": -45,
    "lufs_target": -14.0, "lufs_tol": 1.0, "true_peak_max": -1.0, "clip_level": 0.999, "clip_run": 3,
    "phash_max_dist": 0.12, "phash_shot_cut": 0.5, "phash_min_std": 4.0, "caption_drift_s": 0.15, "caption_hold_s": 0.35,
    "margin_white_frac": 0.001, "banned_word": r"\bmacro", "brand_allow": [], "contact_cols": 4, "contact_rows": 6,
}


def thresholds() -> dict:
    return {**DEFAULTS, **(quality().get("QC") or {})}


class QCError(RuntimeError):
    pass


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {"group": self.group, "name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class Report:
    item: str
    mode: str
    outputs: dict[str, list[Check]] = field(default_factory=dict)
    item_checks: list[Check] = field(default_factory=list)
    sheets: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def verdict_of(checks: list[Check]) -> str:
        return max((c.status for c in checks), key=RANK.__getitem__, default=PASS)

    def verdict(self, output: str | None = None) -> str:
        if output:
            return self.verdict_of(self.outputs[output])
        return self.verdict_of(self.item_checks + [c for cs in self.outputs.values() for c in cs])

    def as_dict(self) -> dict:
        return {"item": self.item, "mode": self.mode, "verdict": self.verdict(), "outputs": {
            o: {"verdict": self.verdict(o), "contact_sheet": self.sheets.get(o), "checks": [c.as_dict() for c in cs]} for o, cs in self.outputs.items()},
            "item_checks": [c.as_dict() for c in self.item_checks]}

    def markdown(self) -> str:
        L = [f"# QC report: {self.item}", "", f"Mode: {self.mode}  |  Generated: {time.strftime('%Y-%m-%d %H:%M')}  |  **Overall: {self.verdict()}**", ""]
        sections = [(f"Output `{o}`: {self.verdict(o)}", cs, self.sheets.get(o)) for o, cs in self.outputs.items()]
        sections.append((f"Item-level checks: {self.verdict_of(self.item_checks)}", self.item_checks, None))
        for title, cs, sheet in sections:
            L += [f"## {title}", ""]
            if sheet:
                L += [f"Contact sheet: `{sheet}`", ""]
            L += ["| Group | Check | Result | Detail |", "|---|---|---|---|"]
            L += [f"| {c.group} | {c.name} | {c.status} | {c.detail.replace('|', '/').replace(chr(10), ' ')} |" for c in cs]
            L.append("")
        bad = [(o, c) for o, cs in [*self.outputs.items(), ("item", self.item_checks)] for c in cs if c.status != PASS]
        L += ["## Items needing attention", ""]
        L += [f"- {c.status} [{o}] {c.group}/{c.name}: {c.detail}" for o, c in bad] if bad else ["- none"]
        return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ffmpeg / ffprobe helpers
def _run(cmd: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=text)


def probe(path: Path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    if r.returncode:
        raise QCError(f"ffprobe failed for {path.name}: {r.stderr[-200:]}")
    return json.loads(r.stdout)


def _ffmpeg_log(path: Path, vf: str | None = None, af: str | None = None, extra: list[str] | None = None) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path)]
    cmd += ["-vf", vf, "-an"] if vf else ["-vn", "-af", af]
    r = _run(cmd + (extra or []) + ["-f", "null", "-"])
    if r.returncode:
        raise QCError(f"ffmpeg analysis failed for {path.name}: {r.stderr[-300:]}")
    return r.stderr


def has_audio(path: Path) -> bool:
    return any(s["codec_type"] == "audio" for s in probe(path)["streams"])


# ---------------------------------------------------------------- 1. spec
def faststart(path: Path) -> bool:
    """True when the moov box comes before mdat (walks the top-level MP4 boxes)."""
    pos, size_total = 0, path.stat().st_size
    seen = {}
    with open(path, "rb") as f:
        while pos + 8 <= size_total:
            f.seek(pos)
            hdr = f.read(16)
            size, kind = int.from_bytes(hdr[:4], "big"), hdr[4:8].decode("latin1")
            if size == 1:
                size = int.from_bytes(hdr[8:16], "big")
            elif size == 0:
                size = size_total - pos
            seen.setdefault(kind, pos)
            if "moov" in seen and "mdat" in seen:
                break
            if size < 8:
                break
            pos += size
    return "moov" in seen and ("mdat" not in seen or seen["moov"] < seen["mdat"])


def check_spec(path: Path, size: tuple[int, int], voice: Path | None, T: dict) -> list[Check]:
    out: list[Check] = []
    d = probe(path)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        return [Check("spec", "video stream", FAIL, "no video stream")]
    bad = []
    if (v["width"], v["height"]) != tuple(size):
        bad.append(f"size {v['width']}x{v['height']} (want {size[0]}x{size[1]})")
    if v["codec_name"] != "h264" or v.get("pix_fmt") != "yuv420p":
        bad.append(f"video {v['codec_name']}/{v.get('pix_fmt')} (want h264/yuv420p)")
    for key in ("r_frame_rate", "avg_frame_rate"):
        n, _, dn = v[key].partition("/")
        if not dn or abs(float(n) / float(dn) - FPS) > 0.01:
            bad.append(f"{key} {v[key]} (want {FPS})")
    out.append(Check("spec", "video format", FAIL if bad else PASS, "; ".join(bad) or f"{size[0]}x{size[1]} h264 {v.get('profile', '')} yuv420p {FPS} fps"))
    if not a:
        out.append(Check("spec", "audio format", FAIL, "no audio stream"))
    else:
        bad = []
        if a["codec_name"] != "aac":
            bad.append(f"codec {a['codec_name']} (want aac)")
        if int(a["sample_rate"]) != 48000:
            bad.append(f"sample rate {a['sample_rate']} (want 48000)")
        out.append(Check("spec", "audio format", FAIL if bad else PASS, "; ".join(bad) or f"aac {a['sample_rate']} Hz {a.get('channels')}ch"))
    dur = float(d["format"]["duration"])
    if voice is not None and voice.is_file():
        vd = sf.info(str(voice)).duration
        diff = dur - vd
        out.append(Check("spec", "duration vs voice", PASS if abs(diff) <= T["duration_tol_s"] else FAIL,
                         f"video {dur:.2f}s, voice {vd:.2f}s, diff {diff:+.2f}s (limit +-{T['duration_tol_s']}s)"))
    else:
        out.append(Check("spec", "duration vs voice", WARN, f"no voice track to compare (video {dur:.2f}s)"))
    if a and v:
        av = float(a.get("duration") or dur)
        vv = float(v.get("duration") or dur)
        out.append(Check("spec", "A/V length", PASS if abs(av - vv) <= 0.25 else WARN, f"video {vv:.2f}s, audio {av:.2f}s"))
    out.append(Check("spec", "faststart", PASS if faststart(path) else FAIL, "moov before mdat" if faststart(path) else "moov atom after mdat (re-mux with -movflags +faststart)"))
    return out


# ---------------------------------------------------------------- 2. black / frozen / silent
def _intervals(log: str, start_re: str, end_re: str, dur: float) -> list[tuple[float, float]]:
    starts = [float(x) for x in re.findall(start_re, log)]
    ends = [float(x) for x in re.findall(end_re, log)]
    out = []
    for i, s in enumerate(starts):
        out.append((s, ends[i] if i < len(ends) else dur))
    return out


def detect_black(path: Path, dur: float, T: dict) -> list[tuple[float, float]]:
    log = _ffmpeg_log(path, vf="blackdetect=d=0.1:pix_th=0.10:pic_th=0.98")
    return _intervals(log, r"black_start:([\d.]+)", r"black_end:([\d.]+)", dur)


def detect_freeze(path: Path, dur: float, T: dict) -> list[tuple[float, float]]:
    log = _ffmpeg_log(path, vf=f"freezedetect=n=-60dB:d={T['freeze_min_s']}")
    return _intervals(log, r"freeze_start: ([\d.]+)", r"freeze_end: ([\d.]+)", dur)


def detect_silence(path: Path, dur: float, T: dict) -> list[tuple[float, float]]:
    log = _ffmpeg_log(path, af=f"silencedetect=noise={T['silence_db']}dB:d={T['silence_min_s']}")
    return _intervals(log, r"silence_start: (-?[\d.]+)", r"silence_end: ([\d.]+)", dur)


def _scene_spans(scenes: list[dict] | None) -> list[dict]:
    out = []
    for sc in scenes or []:
        n = sc.get("narration") or {}
        if n.get("start_s") is not None and n.get("end_s") is not None:
            out.append({"id": sc["id"], "type": sc["type"], "start": n["start_s"], "end": n["end_s"], "hold": bool(sc.get("hold")),
                        "dip": sc.get("transition") == "dip_to_black"})
    return out


def check_black(path: Path, dur: float, scenes: list[dict] | None, T: dict) -> Check:
    spans, bad, ok = _scene_spans(scenes), [], 0
    for s, e in detect_black(path, dur, T):
        if e - s < T["black_min_s"]:
            continue
        edge_fade = (s <= 0.1 or e >= dur - 0.1) and e - s <= T["black_edge_fade_max_s"]
        dip = any(sp["dip"] and (s < sp["end"] + 0.6 and e > sp["end"] - 0.6 or s < sp["start"] + 0.6 and e > sp["start"] - 0.6) for sp in spans)
        if edge_fade or dip:
            ok += 1
        else:
            bad.append(f"{s:.2f}-{e:.2f}s ({e - s:.2f}s)")
    if bad:
        return Check("visual", "black frames", FAIL, f"black >= {T['black_min_s']}s at " + ", ".join(bad))
    return Check("visual", "black frames", PASS, "none >= %.1fs" % T["black_min_s"] + (f" ({ok} intentional fade/dip)" if ok else ""))


def check_freeze(path: Path, dur: float, scenes: list[dict] | None, T: dict) -> Check:
    spans, bad, held = _scene_spans(scenes), [], 0
    for s, e in detect_freeze(path, dur, T):
        if e - s < T["freeze_min_s"]:
            continue
        if any(sp["hold"] and s >= sp["start"] - 0.2 and e <= sp["end"] + 1.2 for sp in spans):
            held += 1
        else:
            bad.append(f"{s:.2f}-{e:.2f}s ({e - s:.2f}s)")
    if bad:
        return Check("visual", "frozen frames", FAIL, f"frozen >= {T['freeze_min_s']}s at " + ", ".join(bad))
    return Check("visual", "frozen frames", PASS, f"none >= {T['freeze_min_s']}s" + (f" ({held} deliberate hold)" if held else ""))


def check_silence(audio_src: Path, dur: float, label: str, T: dict) -> Check:
    if not has_audio(audio_src):
        return Check("audio", label, FAIL, "no audio")
    d = sf.info(str(audio_src)).duration if audio_src.suffix == ".wav" else dur
    hits = [(s, e) for s, e in detect_silence(audio_src, d, T) if e - s >= T["silence_min_s"]]
    if hits:
        return Check("audio", label, FAIL, f"silence > {T['silence_min_s']}s at " + ", ".join(f"{s:.2f}-{e:.2f}s" for s, e in hits))
    return Check("audio", label, PASS, f"no silence > {T['silence_min_s']}s (threshold {T['silence_db']} dB)")


# ---------------------------------------------------------------- 3. loudness
def measure_loudness(path: Path) -> tuple[float, float]:
    """(integrated LUFS, true peak dBTP) from ffmpeg ebur128, summary block."""
    log = _ffmpeg_log(path, af="ebur128=peak=true")
    summary = log[log.rfind("Summary:"):] if "Summary:" in log else log
    i = re.search(r"\bI:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    p = re.search(r"True peak:\s*\n?\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    if not i or not p:
        raise QCError("could not parse ebur128 summary")
    return float(i.group(1)), float(p.group(1))


def clipping(path: Path, T: dict) -> tuple[int, float]:
    """(runs of >= clip_run consecutive samples at/over clip_level in any channel, sample peak). Channels are kept apart
    (a mono downmix of a stereo file would sum the channels and fake an overshoot)."""
    ch = next((s.get("channels", 1) for s in probe(path)["streams"] if s["codec_type"] == "audio"), 1)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-f", "f32le", "-ar", "48000", "-"], capture_output=True)
    if r.returncode:
        raise QCError("audio decode failed")
    x = np.abs(np.frombuffer(r.stdout, dtype="<f4"))
    x = x[: x.size // ch * ch].reshape(-1, ch)
    if not x.size:
        return 0, 0.0
    runs_total = 0
    for c in range(ch):
        hot = (x[:, c] >= T["clip_level"]).astype(np.int8)
        if hot.any():
            edges = np.diff(np.concatenate([[0], hot, [0]]))
            runs_total += int(((np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)) >= T["clip_run"]).sum())
    return runs_total, float(x.max())


def check_loudness(path: Path, T: dict) -> list[Check]:
    if not has_audio(path):
        return [Check("audio", "loudness", FAIL, "no audio")]
    lufs, tp = measure_loudness(path)
    out = [Check("audio", "integrated loudness", PASS if abs(lufs - T["lufs_target"]) <= T["lufs_tol"] else FAIL,
                 f"{lufs:.1f} LUFS (target {T['lufs_target']} +-{T['lufs_tol']})"),
           Check("audio", "true peak", PASS if tp <= T["true_peak_max"] else FAIL, f"{tp:.1f} dBTP (limit {T['true_peak_max']})")]
    runs, peak = clipping(path, T)
    out.append(Check("audio", "clipping", FAIL if runs else PASS,
                     f"{runs} clipped run(s), sample peak {20 * np.log10(max(peak, 1e-9)):.1f} dBFS"))
    return out


# ---------------------------------------------------------------- 4. repeated clips
def check_asset_duplicates(item: Path, output: str) -> Check:
    p = item / "assets.json"
    if not p.is_file():
        return Check("visual", "repeated assets (sha256)", PASS, "no asset ledger (no footage)")
    by: dict[str, list[str]] = {}
    for a in json.loads(p.read_text(encoding="utf-8")).get("assets", []):
        if a.get("output", "main") == output and not a["filename"].startswith("audio/") and a.get("sha256"):
            by.setdefault(a["sha256"], []).append(a["scene"])
    dup = {h: s for h, s in by.items() if len(s) > 1}
    if dup:
        return Check("visual", "repeated assets (sha256)", FAIL, "; ".join(f"{h[:12]} used in scenes {', '.join(s)}" for h, s in dup.items()))
    return Check("visual", "repeated assets (sha256)", PASS, f"{len(by)} distinct clip(s), none reused")


def sample_hashes(path: Path, dur: float) -> tuple[np.ndarray, np.ndarray]:
    """Perceptual signature of one frame per second: a 16x16 grey thumbnail, mean-removed and contrast-normalised
    (robust to brightness / re-encode, unlike a bit hash on smooth gradients). Returns (signatures, raw grey std)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", "fps=1,scale=16:16:flags=area,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode:
        raise QCError("frame sampling failed")
    g = np.frombuffer(r.stdout, dtype=np.uint8)
    g = g[: g.size // 256 * 256].reshape(-1, 256).astype(np.float32)
    std = g.std(axis=1)
    return (g - g.mean(axis=1, keepdims=True)) / np.maximum(std[:, None], 1.0), std


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def find_shots(sig: np.ndarray, std: np.ndarray, spans: list[dict], T: dict) -> list[dict]:
    """Group per-second signatures into shots (new shot at a jump or at a scene start); one representative each."""
    starts = {int(sp["start"]) for sp in spans}
    shots: list[list[int]] = []
    for i in range(len(sig)):
        if i == 0 or i in starts or _dist(sig[i], sig[i - 1]) > T["phash_shot_cut"]:
            shots.append([i])
        else:
            shots[-1].append(i)
    out = []
    for idx in shots:
        mid = idx[len(idx) // 2]
        if std[mid] < T["phash_min_std"]:
            continue    # flat frames are the black / freeze detectors' business
        sc = next((sp for sp in spans if sp["start"] <= mid + 0.5 < sp["end"] + 1e-6), None)
        out.append({"t": mid, "sig": sig[mid], "scene": sc["id"] if sc else None, "type": sc["type"] if sc else None})
    return out


def check_phash(path: Path, dur: float, scenes: list[dict] | None, T: dict) -> Check:
    sig, std = sample_hashes(path, dur)
    spans = _scene_spans(scenes)
    shots = find_shots(sig, std, spans, T)
    fails, warns = [], []
    for i in range(len(shots)):
        for j in range(i + 1, len(shots)):
            a, b = shots[i], shots[j]
            if a["scene"] is not None and a["scene"] == b["scene"]:
                continue    # a clip looped inside one scene is deliberate (the assembler loops short footage)
            d = _dist(a["sig"], b["sig"])
            if d > T["phash_max_dist"]:
                continue
            both_footage = a["type"] == b["type"] == "footage" or (a["type"] is None and b["type"] is None)
            msg = f"t={a['t']}s ~ t={b['t']}s (distance {d:.2f}" + (f", scenes {a['scene']}/{b['scene']}" if a["scene"] else "") + ")"
            (fails if both_footage else warns).append(msg)
    if fails:
        return Check("visual", "near-duplicate shots (perceptual hash)", FAIL, "; ".join(fails))
    if warns:
        return Check("visual", "near-duplicate shots (perceptual hash)", WARN, "similar non-footage shots: " + "; ".join(warns[:4]))
    return Check("visual", "near-duplicate shots (perceptual hash)", PASS, f"{len(shots)} distinct shot(s) sampled at 1 fps")


# ---------------------------------------------------------------- 5. captions
def safe_box(orient: str) -> dict:
    """Safe box in px, read from the render's layout.ts (via layout_check) so QC follows the renderer."""
    from .layout_check import layout_numbers
    return layout_numbers()[0][orient]


def frame_rgb(path: Path, t: float, w: int, h: int) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    if a.size != w * h * 3:
        raise QCError(f"frame at {t:.2f}s unreadable")
    return a.reshape(h, w, 3)


def margin_text_pixels(img: np.ndarray, box: tuple[float, float, float, float]) -> tuple[int, int]:
    """(near-white pixels outside the safe box, margin pixels). Caption and key text are near-white on the dark brand plates,
    so bright pixels in the margin band mean text (or a stamp) is sitting where the platform UI will cover it."""
    h, w, _ = img.shape
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    white = img.min(axis=2) >= 215
    inside = np.zeros((h, w), dtype=bool)
    inside[max(y0, 0):y1, max(x0, 0):x1] = True
    return int((white & ~inside).sum()), int((~inside).sum())


def check_caption_layout(props: dict | None, orient: str, T: dict) -> Check:
    if not props or not props.get("captions"):
        return Check("captions", "layout limits", WARN, "no caption metadata (work/<mode>/props.<output>.json)")
    a5 = quality()["A5_mobile_readability"]
    per_line, max_lines = a5["caption_max_chars_per_line"], a5["caption_max_lines"]
    if props.get("lang") in ("ja", "zh", "ko"):
        per_line //= 2
    bad = []
    for i, c in enumerate(props["captions"]):
        if len(c["lines"]) > max_lines:
            bad.append(f"cue {i + 1}: {len(c['lines'])} lines")
        for ln in c["lines"]:
            if len(" ".join(w["w"] for w in ln)) > per_line:
                bad.append(f"cue {i + 1}: line over {per_line} chars")
        if c["end"] - c["start"] > 3.6 + T["caption_hold_s"] + 0.05:
            bad.append(f"cue {i + 1}: {c['end'] - c['start']:.1f}s on screen")
    from .layout_check import check as layout_problems
    bad += layout_problems(orient, props["captions"])      # caption plate inside the safe box, above the content box, lines fit the width
    box = safe_box(orient)
    return Check("captions", "layout limits", FAIL if bad else PASS,
                 "; ".join(bad[:5]) if bad else f"{len(props['captions'])} cues <= {max_lines} lines x {per_line} chars; renderer safe box {box}")


def check_caption_frames(path: Path, props: dict | None, scenes: list[dict] | None, size: tuple[int, int], orient: str, T: dict) -> Check:
    """OCR-free safe-area check on sampled frames: caption-cue midpoints and the midpoint of every non-footage scene (footage
    art may bleed to the edge by design). Near-white pixels outside the renderer's safe box are text-like content in the UI zone."""
    name = "safe area (sampled frames)"
    sb = safe_box(orient)
    full_w = (props or {}).get("width", size[0])
    k = size[0] / full_w                                    # preview renders are half size
    box = (sb["left"] * k, sb["top"] * k, size[0] - sb["right"] * k, size[1] - sb["bottom"] * k)
    times = [(c["start"] + c["end"]) / 2 for c in (props or {}).get("captions", []) if c["lines"]]
    if len(times) > 8:
        times = [times[int(i)] for i in np.linspace(0, len(times) - 1, 8)]
    for sp in _scene_spans(scenes):
        if sp["type"] != "footage":
            times.append((sp["start"] + sp["end"]) / 2)
    if not times:
        return Check("captions", name, WARN, "no captions or scenes to sample")
    bad, n = [], 0
    for t in times:
        try:
            white, margin = margin_text_pixels(frame_rgb(path, t, *size), box)
        except QCError:
            continue
        n += 1
        if white / max(margin, 1) > T["margin_white_frac"]:
            bad.append(f"t={t:.1f}s: {white} bright px ({white / margin:.2%} of the margin) outside safe box ({box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f})")
    if bad:
        return Check("captions", name, FAIL, "; ".join(bad[:3]))
    return Check("captions", name, PASS if n else WARN, f"no text-like content outside the safe box in {n} sampled frame(s)" if n else "no frame could be sampled")


def parse_srt(text: str) -> list[dict]:
    cues = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = blk.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)", lines[1])
        if not m:
            continue
        g = list(map(int, m.groups()))
        cues.append({"start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, "text": " ".join(lines[2:])})
    return cues


def check_caption_sync(srt: Path | None, scenes: list[dict] | None, T: dict) -> Check:
    if not srt or not srt.is_file():
        return Check("captions", "SRT sync", FAIL, "no .srt file for this output")
    words = [w for sc in scenes or [] for w in ((sc.get("narration") or {}).get("words") or [])]
    cues = parse_srt(srt.read_text(encoding="utf-8"))
    if not cues:
        return Check("captions", "SRT sync", FAIL, "SRT has no cues")
    if not words:
        return Check("captions", "SRT sync", WARN, "no word timings in scenes.timed.json to compare against")
    pos, worst, bad = 0, 0.0, []
    for i, c in enumerate(cues, 1):
        n = len(c["text"].split())
        chunk = words[pos:pos + n]
        pos += n
        if not chunk:
            bad.append(f"cue {i}: more cue words than timed words")
            break
        ds = abs(c["start"] - chunk[0]["start"])
        late = c["end"] - chunk[-1]["end"]     # captions deliberately linger up to caption_hold_s after the last word
        de = max(0.0, -late, late - T["caption_hold_s"])
        worst = max(worst, ds, de)
        if ds > T["caption_drift_s"] or de > T["caption_drift_s"]:
            bad.append(f"cue {i}: start drift {ds * 1000:.0f} ms, end drift {de * 1000:.0f} ms")
    if pos != len(words):
        bad.append(f"{len(words) - pos} timed word(s) not covered by any cue" if pos < len(words) else "cue words exceed timed words")
    if bad:
        return Check("captions", "SRT sync", FAIL, f"{len(bad)} problem(s): " + "; ".join(bad[:4]))
    return Check("captions", "SRT sync", PASS, f"{len(cues)} cues, worst drift {worst * 1000:.0f} ms (limit {T['caption_drift_s'] * 1000:.0f} ms)")


# ---------------------------------------------------------------- 6. data integrity (item level)
def parse_sources_md(item: Path) -> list[dict]:
    """Rows of the markdown tables in sources.md, keyed by lower-cased header. Tolerant: any table counts."""
    p = item / "sources.md"
    if not p.is_file():
        return []
    rows, head = [], None
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip().startswith("|"):
            head = None
            continue
        cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if head is None:
            head = [c.lower() for c in cells]
        else:
            rows.append(dict(zip(head, cells)))
    return rows


def _row_hash(row: dict) -> str | None:
    for k, v in row.items():
        if ("hash" in k or "sha" in k) and re.fullmatch(r"[0-9a-f]{16,64}", v.lower() or ""):
            return v.lower()
    return None


def _row_tag(row: dict) -> str | None:
    for k, v in row.items():
        if any(x in k for x in ("tag", "fresh", "status")) and v.strip().upper() in TAGS:
            return v.strip().upper()
    return None


def _walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_strings(v)


def _used_charts(doc: dict) -> list[tuple[str, str, str]]:
    return [(o["output"], sc["id"], sc["data_ref"]["ref"]) for o in doc["outputs"] for sc in o["scenes"] if sc["type"] == "chart" and sc.get("data_ref")]


def check_data(item: Path, doc: dict, preview: bool) -> list[Check]:
    out: list[Check] = []
    specs = load_chart_specs(item)
    used = _used_charts(doc)
    rows = parse_sources_md(item)
    # data_ref resolves
    miss, kit = [], {}
    for o, sid, ref in used:
        if ref not in specs:
            miss.append(f"{o}/{sid}: '{ref}' not in chart specs")
            continue
        try:
            kit[ref] = to_kit_chart(ref, specs[ref])
        except AssembleError as e:
            miss.append(f"{o}/{sid}: {e}")
    out.append(Check("data", "chart data_ref resolves", FAIL if miss else PASS, "; ".join(miss) or f"{len({r for _, _, r in used})} chart ref(s) resolved ({len(used)} chart scene(s))"))
    # chart hash vs ledger
    problems, checked, nohash = [], 0, []
    for ref in sorted({r for _, _, r in used if r in specs}):
        spec = specs[ref]
        want = chart_hash(spec)
        recorded = []
        if spec.get("chart_hash"):
            recorded.append(("chart_specs", spec["chart_hash"]))
        keys = {ref.lower(), str(spec.get("claim_id", "")).lower()} - {""}
        for r in rows:
            if any(str(v).lower() in keys for k, v in r.items() if any(x in k for x in ("claim", "ref", "chart", "id"))) and _row_hash(r):
                recorded.append(("sources.md", _row_hash(r)))
        if not recorded:
            nohash.append(ref)
        for src, h in recorded:
            checked += 1
            if not want.startswith(h.lower()) and h.lower() != want:
                problems.append(f"{ref}: {src} hash {h[:12]} != computed {want[:12]}")
    if problems:
        out.append(Check("data", "chart hash vs ledger", FAIL, "; ".join(problems)))
    elif nohash:
        out.append(Check("data", "chart hash vs ledger", WARN, f"no recorded hash to compare for {', '.join(nohash)} ({checked} comparison(s) passed); the ledger should carry chart_hash"))
    else:
        out.append(Check("data", "chart hash vs ledger", PASS, f"{checked} recorded hash(es) match the chart data"))
    # tags
    untagged = []
    tagged_rows = [r for r in rows if _row_tag(r)]
    for o in doc["outputs"]:
        for sc in o["scenes"]:
            if sc["type"] == "chart" and sc.get("data_ref") and sc["data_ref"]["ref"] in kit:
                tag = str(kit[sc["data_ref"]["ref"]]["meta"].get("freshness", "")).upper()
                if tag not in TAGS:
                    untagged.append(f"{o['output']}/{sc['id']}: chart tag '{tag}'")
                continue
            for num in re.findall(r"\d[\d,.]*", sc.get("on_screen_text") or ""):
                num = num.rstrip(".,")
                if not any(num in " ".join(map(str, r.values())) for r in tagged_rows):
                    untagged.append(f"{o['output']}/{sc['id']}: '{num}' has no tagged ledger row")
    out.append(Check("data", "numbers carry a freshness tag", FAIL if untagged else PASS,
                     "; ".join(dict.fromkeys(untagged)) or f"charts tagged ({'/'.join(sorted(TAGS))}); {len(tagged_rows)} tagged ledger row(s)"))
    # footage ledger
    assets = load_assets(item)
    bad = []
    for o in doc["outputs"]:
        for sc in o["scenes"]:
            if sc["type"] != "footage":
                continue
            a = assets.get((o["output"], sc["id"]))
            if not a:
                bad.append(f"{o['output']}/{sc['id']}: no ledger entry")
                continue
            lic = a.get("licence") or {}
            miss = [k for k, v in (("provider", a.get("provider")), ("source_url", a.get("source_url")), ("creator", a.get("creator")),
                                   ("licence.name", lic.get("name")), ("download_date", a.get("download_date")), ("sha256", a.get("sha256"))) if not v]
            if not isinstance(a.get("illustrative"), bool):
                miss.append("illustrative")
            f = item / a["filename"]
            if not f.is_file():
                miss.append("file missing")
            elif a.get("sha256") and hashlib.sha256(f.read_bytes()).hexdigest() != a["sha256"]:
                miss.append("sha256 mismatch")
            if miss:
                bad.append(f"{o['output']}/{sc['id']}: " + ", ".join(miss))
    n = sum(1 for o in doc["outputs"] for sc in o["scenes"] if sc["type"] == "footage")
    status = FAIL if bad and not preview else WARN if bad else PASS
    out.append(Check("data", "footage ledger complete", status, "; ".join(bad) + (" (preview: placeholders allowed)" if bad and preview else "") if bad
                     else f"{n} footage scene(s) have complete entries with `illustrative` set" if n else "no footage scenes"))
    return out


def screen_text(item: Path, mode: str, doc: dict) -> dict[str, str]:
    """Everything that appears on screen per output: on-screen text, narration (captions), chart / footage / map labels."""
    wm = item / "work" / mode
    res = {}
    for o in doc["outputs"]:
        p = wm / f"props.{o['output']}.json"
        if p.is_file():
            res[o["output"]] = "\n".join(_walk_strings({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
                                                         if k in ("scenes", "refs", "captions")} | {"hl": None}))
        else:
            res[o["output"]] = "\n".join(_walk_strings([{"t": sc.get("on_screen_text"), "n": sc["narration"]["text"]} for sc in o["scenes"]]))
    return res


def check_deny(item: Path, mode: str, doc: dict, srts: dict[str, Path | None]) -> Check:
    hits = []
    for o, text in screen_text(item, mode, doc).items():
        extra = srts.get(o).read_text(encoding="utf-8") if srts.get(o) and srts[o].is_file() else ""
        for name, rx in DENY:
            if re.search(rx, text + "\n" + extra, re.I):
                hits.append(f"{o}: {name}")
    return Check("data", "deny-listed sources off screen", FAIL if hits else PASS,
                 "; ".join(hits) or "no Schwab / FYERS / NSE feed / Atlas / yfinance / investing.com on screen or in captions")


def banned_word_hits(text: str, T: dict) -> list[str]:
    """Occurrences of the owner-banned word (QC.banned_word, default `\\bmacro`, case-insensitive; also matches macroeconomic(s)
    and #macro) after removing any allowed brand strings (QC.brand_allow, empty by default: no exception)."""
    for b in T["brand_allow"]:
        text = re.sub(re.escape(b), " ", text, flags=re.I)
    return [m.group(0) for m in re.finditer(r"[#\w]*" + T["banned_word"] + r"\w*", text, re.I)]


def check_banned_word(item: Path, mode: str, doc: dict, srts: dict, T: dict) -> Check:
    """The word 'macro' must not appear anywhere the audience sees or hears it: captions/SRT, on-screen text, rendered
    text layers (props), thumbnail text, publishing pack (titles, description, hashtags), meta, narration."""
    src: dict[str, str] = {}
    for o in doc["outputs"]:
        n = o["output"]
        src[f"{n}/narration"] = " ".join(sc["narration"]["text"] for sc in o["scenes"])
        src[f"{n}/on_screen_text"] = " ".join(str(sc.get("on_screen_text") or "") for sc in o["scenes"])
        p = item / "work" / mode / f"props.{n}.json"
        if p.is_file():
            keep = ("scenes", "refs", "captions")
            src[f"{n}/rendered text layers"] = "\n".join(_walk_strings({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if k in keep}))
        if srts.get(n) and srts[n].is_file():
            src[f"{n}/srt"] = srts[n].read_text(encoding="utf-8")
    tp = item / "work" / mode / "props.thumb.json"
    if tp.is_file():
        src["thumbnail"] = "\n".join(_walk_strings({k: v for k, v in json.loads(tp.read_text(encoding="utf-8")).items() if k in ("headline", "scenes")}))
    for name in ("publish.md", "meta.json"):
        if (item / name).is_file():
            src[name] = (item / name).read_text(encoding="utf-8")
    hits = [f"{k}: '{h}'" for k, t in src.items() for h in banned_word_hits(t, T)[:2]]
    if hits:
        return Check("platform", "banned word 'macro'", FAIL, "; ".join(hits[:6]))
    return Check("platform", "banned word 'macro'", PASS,
                 f"not found in {len(src)} audience-facing source(s)" + (f" (allowed: {', '.join(T['brand_allow'])})" if T["brand_allow"] else ""))


# ---------------------------------------------------------------- 7. platform readiness (item level)
def check_platform(item: Path, preview: bool = False) -> list[Check]:
    meta = json.loads((item / "meta.json").read_text(encoding="utf-8")) if (item / "meta.json").is_file() else {}
    pub = (item / "publish.md").read_text(encoding="utf-8") if (item / "publish.md").is_file() else ""
    out = []
    if preview and not (item / "publish.md").is_file():     # previews are not packaged: the pack comes with the final run
        return [Check("platform", n, WARN, "publish.md is written by the final run (preview has no pack)") for n in ("disclaimer", "AI label recommendation")] + [
            Check("platform", "synthetic-voice disclosure", PASS if meta.get("synthetic_voice") is True else FAIL,
                  "meta.json synthetic_voice is true" if meta.get("synthetic_voice") is True else "meta.json synthetic_voice is not true")]
    in_pub = DISCLAIMER in pub or "Not investment advice" in pub
    in_meta = "not investment advice" in str(meta.get("description", "")).lower()
    out.append(Check("platform", "disclaimer", PASS if in_pub or in_meta else FAIL,
                     "disclaimer text present in " + ("publish.md" if in_pub else "meta.json description") if in_pub or in_meta else "disclaimer missing from publish.md and meta.json description"))
    out.append(Check("platform", "synthetic-voice disclosure", PASS if meta.get("synthetic_voice") is True else FAIL,
                     "meta.json synthetic_voice is true" if meta.get("synthetic_voice") is True else "meta.json synthetic_voice is not true (YouTube altered/synthetic flag would be unset)"))
    ai_pub = "AI disclosure recommendation" in pub
    ai_meta = meta.get("ai_label") is True
    out.append(Check("platform", "AI label recommendation", PASS if ai_pub or ai_meta else FAIL,
                     "present in " + ("publish.md" if ai_pub else "meta.json ai_label") if ai_pub or ai_meta else "no AI label recommendation in publish.md and meta.json ai_label is not true"))
    return out


# ---------------------------------------------------------------- 8. contact sheet
def contact_sheet(path: Path, dur: float, dst: Path, T: dict, size: tuple[int, int]) -> Path:
    cols, rows = T["contact_cols"], T["contact_rows"]
    n = cols * rows
    tw = 384 if size[0] >= size[1] else 216
    th = int(round(tw * size[1] / size[0] / 2) * 2)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", f"fps={n}/{dur:.4f}:round=down,scale={tw}:{th}", "-frames:v", str(n),
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    if r.returncode or not r.stdout:
        raise QCError("contact sheet frames failed")
    frames = np.frombuffer(r.stdout, dtype=np.uint8)
    frames = frames[: frames.size // (tw * th * 3) * (tw * th * 3)].reshape(-1, th, tw, 3)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise QCError("Pillow missing: install pillow for the labelled contact sheet") from None
    pad = 18
    img = Image.new("RGB", (cols * tw, rows * (th + pad)), (16, 20, 30))
    d = ImageDraw.Draw(img)
    for i, f in enumerate(frames[:n]):
        x, y = (i % cols) * tw, (i // cols) * (th + pad)
        img.paste(Image.fromarray(f), (x, y + pad))
        t = i * dur / n
        d.text((x + 4, y + 3), f"{int(t // 60)}:{t % 60:04.1f}  #{i + 1}", fill=(230, 235, 245))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    return dst


# ---------------------------------------------------------------- orchestration
def latest_version(dirp: Path, stem: str, ext: str) -> Path | None:
    cands = {dirp / f"{stem}{ext}": 1}
    for p in dirp.glob(f"{stem}.v*{ext}"):
        m = re.fullmatch(rf"{re.escape(stem)}\.v(\d+){re.escape(ext)}", p.name)
        if m:
            cands[p] = int(m.group(1))
    have = {p: v for p, v in cands.items() if p.is_file()}
    return max(have, key=have.get) if have else None


def qc_output(video: Path, *, size: tuple[int, int], orient: str, voice: Path | None, scenes: list[dict] | None, props: dict | None,
              srt: Path | None, item: Path, name: str, T: dict | None = None, sheet_to: Path | None = None) -> tuple[list[Check], Path | None]:
    """All per-output checks for one rendered file. Each detector is guarded so one failure cannot hide the others."""
    T = T or thresholds()
    checks: list[Check] = []

    def guard(group: str, label: str, fn):
        try:
            r = fn()
            checks.extend(r if isinstance(r, list) else [r])
        except Exception as e:     # a broken detector is a FAIL, never a silent pass
            checks.append(Check(group, label, FAIL, f"check could not run: {type(e).__name__}: {e}"))

    guard("spec", "spec", lambda: check_spec(video, size, voice, T))
    dur = float(probe(video)["format"]["duration"])
    guard("visual", "black frames", lambda: check_black(video, dur, scenes, T))
    guard("visual", "frozen frames", lambda: check_freeze(video, dur, scenes, T))
    guard("visual", "repeated assets (sha256)", lambda: check_asset_duplicates(item, name))
    guard("visual", "near-duplicate shots (perceptual hash)", lambda: check_phash(video, dur, scenes, T))
    if voice and voice.is_file():
        guard("audio", "narration silence", lambda: check_silence(voice, dur, "narration silence", T))
    else:
        checks.append(Check("audio", "narration silence", WARN, "no voice track to check; see the mix silence check"))
    guard("audio", "mix silence", lambda: check_silence(video, dur, "mix silence", T))
    guard("audio", "loudness", lambda: check_loudness(video, T))
    guard("captions", "layout limits", lambda: check_caption_layout(props, orient, T))
    guard("captions", "safe area", lambda: check_caption_frames(video, props, scenes, size, orient, T))
    guard("captions", "SRT sync", lambda: check_caption_sync(srt, scenes, T))
    sheet = None
    if sheet_to is not None:
        try:
            sheet = contact_sheet(video, dur, sheet_to, T, size)
        except Exception as e:
            checks.append(Check("review", "contact sheet", WARN, f"not written: {e}"))
    return checks, sheet


def qc_item(item: Path, *, preview: bool = False) -> Report:
    item = Path(item).resolve()
    mode = "preview" if preview else "final"
    timed = item / "work" / "scenes.timed.json"
    sp = timed if timed.is_file() else item / "scenes.json"
    if not sp.is_file():
        raise QCError(f"{item.name}: no scenes.timed.json / scenes.json (run `studio run` first)")
    doc = json.loads(sp.read_text(encoding="utf-8"))
    T = thresholds()
    rep = Report(item.name, mode)
    srts: dict[str, Path | None] = {}
    for o in doc["outputs"]:
        n = o["output"]
        size = ASPECT_SIZE[o["aspect"]]
        orient = "horizontal" if o["aspect"] == "16:9" else "vertical"
        if preview:
            size = (size[0] // 2, size[1] // 2)
            video = item / "preview" / f"{n}.mp4"
            video = latest_version(item / "preview", n, ".mp4") or video
        else:
            video = latest_version(item, n, ".mp4")
        srt = latest_version(item, f"captions.{n}", ".srt") if not preview else None
        if preview:   # previews have no SRT of their own; build it from the cues so the sync check still runs
            pp = item / "work" / mode / f"props.{n}.json"
            if pp.is_file():
                from .captions import cues_to_srt
                srt = item / "work" / mode / f"captions.{n}.srt"
                srt.write_text(cues_to_srt(json.loads(pp.read_text(encoding="utf-8"))["captions"]), encoding="utf-8")
        srts[n] = srt
        if video is None or not video.is_file():
            rep.outputs[n] = [Check("spec", "output file", FAIL, f"{n}.mp4 not found in {item.name}{'/preview' if preview else ''}")]
            continue
        voice = next((item / v for v in (f"voice.{n}.wav", "voice.wav") if (item / v).is_file()), None)
        pp = item / "work" / mode / f"props.{n}.json"
        props = json.loads(pp.read_text(encoding="utf-8")) if pp.is_file() else None
        checks, sheet = qc_output(video, size=size, orient=orient, voice=voice, scenes=o["scenes"], props=props, srt=srt, item=item, name=n, T=T,
                                  sheet_to=item / (f"contact_sheet.{n}.png"))
        rep.outputs[n] = checks
        if sheet:
            rep.sheets[n] = sheet.name
    try:
        rep.item_checks += check_data(item, doc, preview)
    except Exception as e:
        rep.item_checks.append(Check("data", "data integrity", FAIL, f"check could not run: {type(e).__name__}: {e}"))
    try:
        rep.item_checks.append(check_deny(item, mode, doc, srts))
    except Exception as e:
        rep.item_checks.append(Check("data", "deny-listed sources off screen", FAIL, f"check could not run: {e}"))
    try:
        rep.item_checks.append(check_banned_word(item, mode, doc, srts, T))
    except Exception as e:
        rep.item_checks.append(Check("platform", "banned word 'macro'", FAIL, f"check could not run: {e}"))
    rep.item_checks += check_platform(item, preview)
    (item / "qc.json").write_text(json.dumps(rep.as_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    (item / "qc.md").write_text(rep.markdown(), encoding="utf-8")
    return rep


def cmd_studio_qc(a) -> int:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"qc: {tool} not found")
            return 2
    try:
        rep = qc_item(Path(a.item), preview=a.preview)
    except QCError as e:
        print(f"qc: {e}")
        return 2
    print(f"QC {rep.verdict()}: " + ", ".join(f"{o}={rep.verdict(o)}" for o in rep.outputs) + f"  (qc.md in {a.item})")
    return 1 if rep.verdict() == FAIL else 0
