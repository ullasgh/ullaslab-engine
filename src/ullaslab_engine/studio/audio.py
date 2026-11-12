"""Audio for the studio: stems (narration / music / sfx stay separate files), an envelope duck (music about 20 dB under the voice), two-pass loudnorm.

Licences: music comes from config/music_ledger.yaml (Pixabay Music with the licence recorded, or CC0) or, when no track
is available, an in-house generated pad (CC0, zero cost). YouTube Audio Library tracks are refused (YouTube-only use).
SFX are synthesised in-house with ffmpeg lavfi (no third-party files)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import soundfile as sf
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
    if t.get("sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(t["sha256"]).lower()):
        raise AudioError(f"music '{t['id']}': sha256 must be 64 hex characters")


def pick_track(ledger: list[dict], mood: str | None = None, music_dir: Path = MUSIC_DIR) -> dict | None:
    ok = []
    for t in ledger:
        check_track(t)
        f = music_dir / t["file"]
        if f.is_file():
            if t.get("sha256") and hashlib.sha256(f.read_bytes()).hexdigest() != str(t["sha256"]).lower():
                raise AudioError(f"music '{t['id']}': {t['file']} does not match the recorded sha256")
            ok.append(t)
    if not ok:
        return None
    return next((t for t in ok if mood and mood in t.get("mood", [])), ok[0])


# ------------------------------------------------------------------ private R2 fetch
# Licensed tracks are not in git. They sit in a PRIVATE R2 bucket under assets/music/<file> (no public r2.dev, no custom domain).
# Cloud renders use S3-compatible read-only keys from env; the owner's Mac falls back to wrangler's existing login.
R2_PREFIX = "assets/music/"
R2_DEFAULT_BUCKET = "ullaslab-private"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _r2_get_s3(key: str, dst: Path, env: dict) -> None:
    import boto3  # optional extra: pip install ullaslab-engine[cloud]
    s3 = boto3.client("s3", endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", region_name="auto",
                      aws_access_key_id=env["R2_ACCESS_KEY_ID"], aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"])
    s3.download_file(env.get("R2_BUCKET") or R2_DEFAULT_BUCKET, key, str(dst))


def _r2_get_wrangler(key: str, dst: Path, env: dict) -> None:
    exe = shutil.which("wrangler")
    cmd = [exe] if exe else ["npx", "--yes", "wrangler"]
    bucket = env.get("R2_BUCKET") or R2_DEFAULT_BUCKET
    r = subprocess.run(cmd + ["r2", "object", "get", f"{bucket}/{key}", "--file", str(dst), "--remote"],
                       capture_output=True, text=True, timeout=300, check=False)
    if r.returncode != 0:
        raise AudioError("wrangler r2 object get failed: " + (r.stderr or r.stdout).strip()[-300:])


def fetch_missing_tracks(ledger: list[dict], music_dir: Path = MUSIC_DIR, env: dict | None = None,
                         getter=None) -> dict:
    """Download every ledger track that is not in music_dir from private R2 and verify its sha256.
    Returns {"fetched": [ids], "failed": {id: reason}}. Never raises for a failed download: the caller must surface `failed` loudly."""
    env = dict(os.environ) if env is None else env
    out: dict = {"fetched": [], "failed": {}}
    missing = [t for t in ledger if t.get("file") and not (music_dir / t["file"]).is_file()]
    if not missing:
        return out
    if env.get("ULLASLAB_MUSIC_FETCH") == "off":   # WP8 Actions: the music came by presigned URL; no R2 keys, no wrangler
        out["failed"] = {t.get("id", "?"): "fetch off (ULLASLAB_MUSIC_FETCH=off)" for t in missing}
        return out
    if getter is None:
        have_s3 = all(env.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"))
        getter = _r2_get_s3 if have_s3 else _r2_get_wrangler
    music_dir.mkdir(parents=True, exist_ok=True)
    for t in missing:
        tmp = None
        try:
            check_track(t)
            fd, name = tempfile.mkstemp(dir=music_dir, suffix=".part")
            os.close(fd)
            tmp = Path(name)
            tmp.unlink()   # wrangler refuses to overwrite; boto3 does not care
            getter(R2_PREFIX + t["file"], tmp, env)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                raise AudioError("downloaded file is empty or missing")
            if t.get("sha256") and _sha256_file(tmp) != str(t["sha256"]).lower():
                raise AudioError("downloaded file does not match the ledger sha256")
            tmp.replace(music_dir / t["file"])
            out["fetched"].append(t["id"])
        except Exception as e:   # noqa: BLE001 - every failure must be reported, never swallowed
            out["failed"][t.get("id", "?")] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
    return out


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
MIX_DEFAULTS = {"music_below_voice_db": 20.0, "rise_db": 9.0, "pause_min_s": 1.0, "intro_s": 2.0, "outro_s": 3.0, "attack_s": 0.30,
                "release_s": 1.20, "lookahead_s": 0.25, "speech_floor_db": -42.0}
FRAME_S = 0.01


def mix_cfg() -> dict:
    from ..config import quality
    return {**MIX_DEFAULTS, **(quality().get("MIX") or {})}


def _db(x: float) -> float:
    return 20 * np.log10(max(float(x), 1e-9))


def _lufs(x: np.ndarray, sr: int) -> float:
    """K-weighted loudness (what a listener and the ebur128 meter hear), so the voice-to-music gap is perceptual, not raw RMS."""
    import pyloudnorm as pyln
    x = np.asarray(x, dtype=np.float64)
    if len(x) < int(0.5 * sr):
        x = np.pad(x, (0, int(0.5 * sr) - len(x)))
    v = pyln.Meter(sr).integrated_loudness(x)
    return float(v) if np.isfinite(v) else -70.0


def speech_mask(nar: np.ndarray, sr: int, cfg: dict) -> np.ndarray:
    """Per 10 ms frame: True while narration is active. Gaps shorter than pause_min_s are bridged (stay ducked)."""
    n = int(sr * FRAME_S)
    k = len(nar) // n
    rms = np.sqrt((nar[: k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-12)
    on = 20 * np.log10(rms) > cfg["speech_floor_db"]
    out, i = on.copy(), 0
    idx = np.flatnonzero(on)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a and (b - a - 1) * FRAME_S <= cfg["pause_min_s"]:
            out[a:b] = True
    return out


def duck_gain_db(nar: np.ndarray, music: np.ndarray, sr: int, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """Per-frame gain (dB) for the music bed. While narration is active the bed is `music_below_voice_db` under the voice
    (measured on the voice's active RMS vs the bed's RMS); in the intro, the outro and pauses longer than pause_min_s it rises by
    rise_db. Lookahead plus separate attack (down) and release (up) one-pole smoothing keeps every move gentle."""
    cfg = cfg or mix_cfg()
    mask = speech_mask(nar, sr, cfg)
    nfr = len(mask)
    if not mask.any():
        return np.full(nfr, -30.0), {"voice_lufs": None, "base_gain_db": -30.0}
    n = int(sr * FRAME_S)
    voice_db = _lufs(np.concatenate([nar[i * n:(i + 1) * n] for i in np.flatnonzero(mask)]), sr)
    music_db = _lufs(music, sr)
    base = voice_db - cfg["music_below_voice_db"] - music_db
    t = np.arange(nfr) * FRAME_S
    total = nfr * FRAME_S
    rise = ~mask
    rise |= (t < cfg["intro_s"]) & ~mask
    rise |= (t > total - cfg["outro_s"]) & ~mask
    # Level-follow: a bed that swells (slow beats in a pad, a louder bar) is brought back to its average, so the gap to the voice holds.
    k = int(2.0 / FRAME_S)
    e = np.sqrt((music[: nfr * n].reshape(nfr, n) ** 2).mean(axis=1) + 1e-12) if len(music) >= nfr * n else np.full(nfr, 1e-4)
    loc = np.sqrt(np.convolve(np.pad(e ** 2, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")[:nfr] + 1e-12)
    follow = np.clip(20 * np.log10(np.sqrt(np.mean(e ** 2)) + 1e-9) - 20 * np.log10(loc + 1e-9), -8.0, 6.0)
    target = np.where(rise, base + cfg["rise_db"], base) + follow
    la = max(1, int(cfg["lookahead_s"] / FRAME_S))          # start ducking before the first word
    pad = np.concatenate([target, np.full(la, target[-1])])
    tgt = np.minimum.reduce([pad[j:j + nfr] for j in range(la + 1)])
    ka, kr = np.exp(-FRAME_S / cfg["attack_s"]), np.exp(-FRAME_S / cfg["release_s"])
    g = np.empty(nfr)
    cur = tgt[0]
    for i, x in enumerate(tgt):
        c = ka if x < cur else kr
        cur = c * cur + (1 - c) * x
        g[i] = cur
    return g, {"voice_lufs": round(voice_db, 2), "music_lufs": round(music_db, 2), "base_gain_db": round(base, 2)}


def apply_duck(nar_path: Path, mus_path: Path, dst: Path, cfg: dict | None = None) -> dict:
    """Write the ducked music stem (same length as the music stem) and return the levels used."""
    nar, sr = sf.read(str(nar_path), dtype="float32", always_2d=True)
    mus, sr2 = sf.read(str(mus_path), dtype="float32", always_2d=True)
    if sr != sr2:
        raise AudioError(f"narration {sr} Hz != music {sr2} Hz")
    g, info = duck_gain_db(nar.mean(axis=1), mus.mean(axis=1), sr, cfg)
    per = np.repeat(10 ** (g / 20), int(sr * FRAME_S))
    per = np.concatenate([per, np.full(max(0, len(mus) - len(per)), per[-1])])[: len(mus)]
    sf.write(str(dst), (mus * per[:, None]).astype(np.float32), sr)
    return info


def mix_graph() -> str:
    """Inputs: 0 narration, 1 music (already ducked by apply_duck), 2 sfx. Plain sum; the duck is done upstream."""
    return ("[0:a]pan=stereo|c0=c0|c1=c0[narst];"
            "[2:a]pan=stereo|c0=c0|c1=c0[sfxst];"
            "[narst][1:a][sfxst]amix=inputs=3:normalize=0:duration=first[mix]")


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


def mux_cmd(video: Path, audio: Path, dst: Path, seconds: float | None = None) -> list[str]:
    """H.264 video copied (already High / yuv420p / 30 fps), AAC 48 kHz, faststart.
    No `-shortest`: with a stream-copied video it ended the file up to a few frames early (the last frames and the end of the
    sign-off were lost). The audio stem is built to the exact video length; `seconds` (the video length) caps the audio."""
    cap = ["-t", f"{seconds:.6f}"] if seconds else []
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), *cap, "-movflags", "+faststart", str(dst)]
