"""Audio for the studio: stems (narration / music / sfx stay separate files), sidechain ducking, two-pass loudnorm.

Licences: music comes from config/music_ledger.yaml (Pixabay Music with the licence recorded, or CC0) or, when no track
is available, an in-house generated pad (CC0, zero cost). YouTube Audio Library tracks are refused (YouTube-only use).
SFX are synthesised in-house with ffmpeg lavfi (no third-party files)."""
from __future__ import annotations
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import yaml

from ..config import CONFIG_DIR, ROOT

TARGET_LUFS = -14.0
TP_TARGET = -1.5          # loudnorm ceiling; the spec limit is -1.0 dBTP and ffmpeg's true-peak estimate has ~0.3 dB slack
TP_LIMIT = -1.0
SR = 48000
MUSIC_DIR = ROOT / "assets" / "music"

# In-house SFX: lavfi graphs (all mono 48 kHz). Level is the gain applied at placement; kept restrained.
SFX = {
    "tick": ("sine=f=1900:d=0.05:r=48000,afade=t=out:st=0.01:d=0.04", 0.35),
    "whoosh": ("anoisesrc=d=0.7:c=pink:a=0.6:r=48000,highpass=f=250,lowpass=f=5000,afade=t=in:d=0.28,afade=t=out:st=0.28:d=0.42", 0.30),
    "riser": ("aevalsrc='0.5*sin(2*PI*(160+260*t)*t)*min(1\\,t/1.2)':d=1.5:s=48000,afade=t=out:st=1.3:d=0.2", 0.22),
    "hit": ("aevalsrc='0.9*sin(2*PI*58*t)*exp(-7*t)':d=0.7:s=48000", 0.45),
    "page_turn": ("anoisesrc=d=0.28:c=white:a=0.5:r=48000,highpass=f=2600,afade=t=in:d=0.04,afade=t=out:st=0.08:d=0.2", 0.22),
    "ambient_low": ("aevalsrc='0.35*sin(2*PI*55*t)+0.25*sin(2*PI*82.4*t)':d=3:s=48000,afade=t=in:d=1,afade=t=out:st=1.8:d=1.2", 0.30),
}
SFX_LEAD = {"riser": 1.4}     # seconds the sound starts before the transition so that it peaks on the cut
SFX_PROVENANCE = {"name": "Generated in-house with ffmpeg lavfi (no third-party audio)", "licence": "CC0 1.0 (own work)",
                  "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/", "cost_usd": 0}


class AudioError(RuntimeError):
    pass


def run(cmd: list[str], what: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise AudioError(f"{what} failed: {r.stderr[-400:]}")
    return r.stderr


# ------------------------------------------------------------------ music ledger
def load_music_ledger(path: Path | None = None) -> list[dict]:
    p = path or CONFIG_DIR / "music_ledger.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("tracks", []) if p.is_file() else []


def check_track(t: dict) -> None:
    """Licence gate: a recorded licence and a non-YouTube-Audio-Library source are mandatory."""
    blob = " ".join(str(t.get(k, "")) for k in ("source", "licence", "licence_url", "source_url", "title")).lower()
    if "youtube" in blob or "audio library" in blob:
        raise AudioError(f"music '{t.get('id')}': YouTube Audio Library tracks are YouTube-only and must not be used in reels")
    for k in ("id", "file", "title", "artist", "source", "licence", "licence_url", "source_url", "downloaded"):
        if not t.get(k):
            raise AudioError(f"music '{t.get('id', '?')}': ledger field '{k}' missing (licence must be recorded)")
    if t["source"].lower() not in ("pixabay", "cc0"):
        raise AudioError(f"music '{t['id']}': source must be pixabay or cc0, got '{t['source']}'")


def pick_track(ledger: list[dict], mood: str | None = None, music_dir: Path = MUSIC_DIR) -> dict | None:
    ok = []
    for t in ledger:
        check_track(t)
        if (music_dir / t["file"]).is_file():
            ok.append(t)
    if not ok:
        return None
    return next((t for t in ok if mood and mood in t.get("mood", [])), ok[0])


def generated_track() -> dict:
    return {"id": "generated-pad", "file": None, "title": "UllasLab generated pad", "artist": "UllasLab (ffmpeg lavfi)",
            "source": "generated", "licence": "CC0 1.0 (own work)", "licence_url": SFX_PROVENANCE["licence_url"],
            "source_url": "", "downloaded": date.today().isoformat()}


def generate_pad(dst: Path, seconds: float) -> Path:
    expr = ("0.22*sin(2*PI*110*t)*(0.7+0.3*sin(2*PI*0.11*t))+0.16*sin(2*PI*164.81*t)*(0.7+0.3*sin(2*PI*0.083*t+1))"
            "+0.12*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.07*t+2))")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d={seconds:.2f}:s={SR}",
         "-af", "lowpass=f=900", "-ac", "1", str(dst)], "pad generation")
    return dst


# ------------------------------------------------------------------ stems
def make_sfx_library(dst: Path) -> dict[str, Path]:
    dst.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (graph, _) in SFX.items():
        p = dst / f"{name}.wav"
        if not p.is_file():
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", graph, "-ar", str(SR), "-ac", "1", str(p)], f"sfx {name}")
        out[name] = p
    return out


def sfx_events(scenes: list[dict]) -> list[tuple[str, float]]:
    """(name, start_s) for every scene whose director sfx is not 'none'. The first scene has no transition; sounds
    land on the scene's start (risers lead in so they peak on it)."""
    ev = []
    for k, sc in enumerate(scenes):
        name = sc.get("sfx", "none")
        if name in ("none", None) or name not in SFX:
            continue
        t = sc["narration"]["start_s"] - SFX_LEAD.get(name, 0.0)
        ev.append((name, max(0.0, round(t, 3))))
    return ev


def sfx_stem_cmd(events: list[tuple[str, float]], lib: dict[str, Path], total_s: float, dst: Path) -> list[str]:
    """ffmpeg command mixing placed SFX into one stem as long as the video."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", f"{total_s:.3f}", "-i", f"anullsrc=r={SR}:cl=mono"]
    parts = ["[0:a]anull[base]"]
    labels = ["[base]"]
    for i, (name, t) in enumerate(events, 1):
        cmd += ["-i", str(lib[name])]
        parts.append(f"[{i}:a]volume={SFX[name][1]},adelay={int(round(t * 1000))}:all=1[e{i}]")
        labels.append(f"[e{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first[out]")
    return cmd + ["-filter_complex", ";".join(parts), "-map", "[out]", "-ar", str(SR), "-ac", "1", str(dst)]


def music_stem_cmd(src: Path, total_s: float, dst: Path) -> list[str]:
    """Loop/trim a music file to the video length with a 1 s fade-in and 2 s fade-out, mono-safe 48 kHz."""
    fo = max(0.0, total_s - 2.0)
    return ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{total_s:.3f}",
            "-af", f"afade=t=in:d=1,afade=t=out:st={fo:.3f}:d=2", "-ar", str(SR), "-ac", "2", str(dst)]


def narration_stem_cmd(src: Path, total_s: float, dst: Path) -> list[str]:
    """Narration on its own stem: resampled to 48 kHz and padded with silence to the video length."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"aresample={SR},apad=whole_dur={total_s:.3f}",
            "-t", f"{total_s:.3f}", "-ac", "1", str(dst)]


# ------------------------------------------------------------------ mix
MUSIC_GAIN = 0.34


def mix_graph() -> str:
    """Inputs: 0 narration, 1 music, 2 sfx. Music is sidechain-compressed by the narration (ducking), then summed."""
    return (f"[0:a]asplit=2[nar][key];"
            f"[1:a]volume={MUSIC_GAIN}[mus];"
            "[mus][key]sidechaincompress=threshold=0.015:ratio=9:attack=25:release=450:makeup=1[duck];"
            "[nar]pan=stereo|c0=c0|c1=c0[narst];"
            "[2:a]pan=stereo|c0=c0|c1=c0[sfxst];"
            "[narst][duck][sfxst]amix=inputs=3:normalize=0:duration=first[mix]")


def mix_cmd(nar: Path, mus: Path, sfx: Path, dst: Path) -> list[str]:
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(nar), "-i", str(mus), "-i", str(sfx), "-filter_complex", mix_graph() + ";[mix]anull[out]",
            "-map", "[out]", "-ar", str(SR), "-ac", "2", str(dst)]


def loudnorm_filter(measured: dict | None = None) -> str:
    base = f"loudnorm=I={TARGET_LUFS}:TP={TP_TARGET}:LRA=11"
    if not measured:
        return base + ":print_format=json"
    return (f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true:print_format=summary")


def parse_loudnorm_json(stderr: str) -> dict:
    m = list(re.finditer(r"\{[^{}]*\}", stderr, re.S))
    if not m:
        raise AudioError("loudnorm pass 1 printed no JSON")
    return json.loads(m[-1].group(0))


def loudnorm_two_pass(src: Path, dst: Path) -> dict:
    """Pass 1 measures, pass 2 applies linear gain to -14 LUFS / TP <= -1.5 dBTP. Returns the pass-1 measurement."""
    err = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", loudnorm_filter(), "-f", "null", "-"], "loudnorm pass 1")
    meas = parse_loudnorm_json(err)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", loudnorm_filter(meas) + f",aresample={SR}", "-ar", str(SR), "-ac", "2", str(dst)],
        "loudnorm pass 2")
    return meas


def measure(path: Path) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) via ebur128."""
    err = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], "ebur128")
    tail = err[err.rindex("Summary:"):] if "Summary:" in err else err
    i = re.search(r"\bI:\s+(-?[\d.]+)\s+LUFS", tail)
    p = re.search(r"True peak:.*?Peak:\s+(-?[\d.]+)\s+dBFS", tail, re.S)
    if not i or not p:
        raise AudioError("could not parse ebur128 summary")
    return {"lufs": float(i.group(1)), "true_peak_dbtp": float(p.group(1))}


def mux_cmd(video: Path, audio: Path, dst: Path) -> list[str]:
    """H.264 video copied (already High / yuv420p / 30 fps), AAC 48 kHz, faststart."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-shortest", "-movflags", "+faststart", str(dst)]
