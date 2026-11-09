"""WP14: Instagram Story stage. A 10-15 s 1080x1920 clip: brand text card (Remotion `Story`) over the
narration of the Reel's hook scene plus an optional royalty-free music bed, ducked under the voice.
Content never leaves the runner except the finished mp4 and a numbers-only QA json (public repo rule)."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .audio import Wav, loudness_lufs, normalize_loudness, resample, true_peak_dbtp
from .bundle import load_bundle
from .config import ROOT, quality

SR = 48000
STORY_ZONE = json.loads((ROOT / "config" / "safe_zones.json").read_text())["story"]
STRINGS = {"en": {"cta": "New Reel on our profile", "ai": "AI-generated voice", "source": "Source"},
           "hi": {"cta": "हमारी प्रोफ़ाइल पर नई रील", "ai": "एआई-निर्मित आवाज़", "source": "स्रोत"}}
_SENT = re.compile(r"^(.*?[.।!?])(\s|$)", re.S)


def cfg() -> dict:
    return quality()["S_story"]


def story_langs(m: dict) -> list[str]:
    """Languages with story text in the manifest (the source language first)."""
    txt = (m.get("story") or {}).get("text") or {}
    return [lg for lg in m["languages"] if lg in txt]


def pick_window(tl: dict, duration_cap: float | None = None) -> tuple[float, float]:
    """Voice window = the hook scene (first scene), capped. Hook timing marks drive the pick."""
    c = cfg()
    cap = duration_cap or c["voice_max_s"]
    sc = tl["scenes"][0]
    a = float(sc["start"])
    b = min(float(sc["end"]), a + cap)
    return a, max(b, a + 1.0)


def story_duration(win: tuple[float, float]) -> float:
    c = cfg()
    return float(min(c["duration_max_s"], max(c["duration_min_s"], (win[1] - win[0]) + 2.5)))


def voice_env(x: np.ndarray, sr: int, attack: float, release: float, thr_db: float = -45.0) -> np.ndarray:
    """0..1 envelope: 1 while voice is present, smoothed with attack/release."""
    frame = max(1, int(sr * 0.01))
    n = len(x) // frame + 1
    pad = np.zeros(n * frame, dtype=np.float32)
    pad[: len(x)] = x
    rms = np.sqrt(np.mean(pad.reshape(n, frame) ** 2, axis=1))
    on = (rms > 10 ** (thr_db / 20)).astype(np.float32)
    a, r = np.exp(-0.01 / max(attack, 1e-3)), np.exp(-0.01 / max(release, 1e-3))
    env = np.zeros(n, dtype=np.float32)
    cur = 0.0
    for i, v in enumerate(on):
        k = a if v > cur else r
        cur = k * cur + (1 - k) * v
        env[i] = cur
    return np.repeat(env, frame)[: len(x)]


def loop_to(w: Wav, n: int) -> np.ndarray:
    if len(w.samples) == 0:
        return np.zeros(n, dtype=np.float32)
    reps = int(np.ceil(n / len(w.samples)))
    return np.tile(w.samples, reps)[:n]


def mix(voice: Wav | None, music: Wav | None, duration: float, voice_start: float = 0.0) -> Wav:
    """Voice at t=voice_start, music bed ducked by duck_db under it, fades, normalised to -15 LUFS."""
    c = cfg()
    n = int(round(duration * SR))
    out = np.zeros(n, dtype=np.float64)
    v = None
    if voice is not None:
        vw = resample(voice, SR)
        v = np.zeros(n, dtype=np.float64)
        seg = vw.samples[: max(0, n - int(voice_start * SR))].astype(np.float64)
        i = int(voice_start * SR)
        f = min(len(seg), int(0.15 * SR))
        if f:
            seg[:f] *= np.linspace(0, 1, f)
            seg[-f:] *= np.linspace(1, 0, f)
        v[i:i + len(seg)] = seg
        vn = normalize_loudness(Wav(v.astype(np.float32), SR), target=-16.0).samples.astype(np.float64)
        out += vn
    if music is not None:
        mw = resample(music, SR)
        m = loop_to(mw, n).astype(np.float64)
        g = 10 ** (c["duck_db"] / 20)
        env = voice_env(v.astype(np.float32), SR, c["duck_attack_s"], c["duck_release_s"]) if v is not None else np.zeros(n)
        mgain = 1.0 - env * (1.0 - g)
        m = m * mgain
        if v is not None:  # bed starts 6 dB under the narration's own level, then ducks by duck_db while it speaks
            act = vn[np.abs(vn) > 1e-4]
            vr = float(np.sqrt(np.mean(act ** 2))) if len(act) else 0.1
            m = m * (vr * 10 ** (-6 / 20) / max(float(np.sqrt(np.mean(m ** 2))), 1e-9))
        out += m
    fi, fo = int(c["fade_in_s"] * SR), int(c["fade_out_s"] * SR)
    out[:fi] *= np.linspace(0, 1, fi)
    out[-fo:] *= np.linspace(1, 0, fo)
    w = Wav(out.astype(np.float32), SR)
    if float(np.max(np.abs(w.samples))) < 1e-6:
        return w
    return normalize_loudness(w, target=float(c["loudness_lufs"]), ceiling=float(c["true_peak_max_dbtp"]))


def load_music(path: Path | None) -> Wav | None:
    if path is None or not Path(path).exists():
        return None
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return Wav(data.mean(axis=1).astype(np.float32), sr)


def story_strings(lang: str) -> dict:
    return STRINGS.get(lang, STRINGS["en"])


def edu_line(disclaimer: dict | str, lang: str) -> str:
    d = disclaimer if isinstance(disclaimer, str) else (disclaimer.get(lang) or disclaimer.get("en") or "")
    mm = _SENT.match(d.strip())
    return (mm.group(1) if mm else d.strip()).rstrip(".।") or "Education only"


_SOURCE_PREFIX = re.compile(r"^\s*(?:sources?|fuente|fonte|स्रोत|ஆதாரம்|మూలం|ಮೂಲ|ഉറവിടം|সূত্র|સ્ત્રોત|المصدر|出典)\s*[:：\-–—]\s*", re.I)


def clean_source_name(name: str) -> str:
    """Drop a leading 'Source:' so the stamp does not read 'Source: Source: X'."""
    out = name.strip()
    for _ in range(3):
        nxt = _SOURCE_PREFIX.sub("", out, count=1)
        if nxt == out:
            break
        out = nxt
    return out or name.strip()


def source_stamp(m: dict, lang: str) -> str:
    for sc in m["scenes"]:
        cd = sc.get("chart_data")
        if cd:
            return f"{story_strings(lang)['source']}: {clean_source_name(cd['source']['name'])}"
    return ""


def make_props(m: dict, lang: str, duration: float, audio_name: str | None) -> dict:
    st = m["story"]
    sub = (st.get("sub") or {}).get(lang, "")
    S = story_strings(lang)
    return {"lang": lang, "text": st["text"][lang], "sub": sub, "source": source_stamp(m, lang),
            "edu": edu_line(m["disclaimer"], lang), "cta": S["cta"],
            "aiVoice": S["ai"] if m.get("synthetic_voice") else "", "durationS": duration,
            "audio": audio_name or "", "rtl": lang == "ar", "accent": "#4FD1C5"}


# -- QA ---------------------------------------------------------------------------------------
def _chk(name, value, limit, ok) -> dict:
    return {"name": name, "value": round(value, 3) if isinstance(value, float) else value, "limit": limit, "passed": bool(ok)}


def contrast(fg: str, bg: str) -> float:
    from .qa import contrast_ratio
    return contrast_ratio(fg, bg)


def qa_story(props: dict, audio: Wav | None, layout: dict | None, video_duration: float | None = None) -> dict:
    c = cfg()
    dur = video_duration if video_duration is not None else props["durationS"]
    checks = [_chk("duration_s", dur, f"{c['duration_min_s']}-{c['duration_max_s']}", c["duration_min_s"] <= dur <= c["duration_max_s"] + 0.1),
              _chk("text_chars", len(props["text"]), c["max_text_chars"], 0 < len(props["text"]) <= c["max_text_chars"]),
              _chk("sub_chars", len(props["sub"]), c["max_sub_chars"], len(props["sub"]) <= c["max_sub_chars"]),
              _chk("cta_present", bool(props["cta"]), True, bool(props["cta"])),
              _chk("education_line_present", bool(props["edu"]), True, bool(props["edu"]))]
    if audio is not None:
        lufs, tp = loudness_lufs(audio), true_peak_dbtp(audio)
        lo, hi = c["loudness_lufs"] - c["loudness_tolerance_lu"], c["loudness_lufs"] + c["loudness_tolerance_lu"]
        checks += [_chk("lufs", lufs, f"{lo}..{hi}", lo <= lufs <= hi),
                   _chk("true_peak_dbtp", tp, c["true_peak_max_dbtp"], tp <= c["true_peak_max_dbtp"])]
    if layout is None:
        checks.append(_chk("layout_audit", "missing", "present", False))
    else:
        z = STORY_ZONE
        out = small = low = 0
        for fr in layout["frames"]:
            for e in fr["elements"]:
                if e["role"] == "bg":
                    continue
                if (e["x"] < z["sides"] - 0.5 or e["x"] + e["w"] > layout["width"] - z["sides"] + 0.5
                        or e["y"] < z["top"] - 0.5 or e["y"] + e["h"] > layout["height"] - z["bottom"] + 0.5):
                    out += 1
                if e["role"] in ("headline", "body") and e["fontPx"] < c["min_text_px"] - 0.01:
                    small += 1
                if e["role"] in ("label", "stamp") and e["fontPx"] < c["min_label_px"] - 0.01:
                    small += 1
                if e.get("fg") and e.get("bg") and contrast(e["fg"], e["bg"]) < c["min_contrast_ratio"]:
                    low += 1
        checks += [_chk("elements_outside_story_safe_zone", out, 0, out == 0),
                   _chk("text_below_min_px", small, 0, small == 0),
                   _chk("contrast_failures", low, 0, low == 0),
                   _chk("frame_size", f"{layout['width']}x{layout['height']}", "1080x1920", (layout["width"], layout["height"]) == (1080, 1920)),
                   _chk("audited_frames", len(layout["frames"]), ">=1", len(layout["frames"]) >= 1)]
    return {"kind": "story", "lang": props["lang"], "passed": all(x["passed"] for x in checks), "checks": checks}


# -- stage ------------------------------------------------------------------------------------
def stage_story(work: Path, lang: str, music: Path | None = None, render: bool = True) -> dict | None:
    """Mix audio, render story_<lang>.mp4 (work/<lang>/story/video.mp4) and write qa.json. None if the language has no story."""
    from .pipeline import jdump, jload
    m = load_bundle(work / "bundle")
    if lang not in story_langs(m):
        return None
    out = (work / lang / "story").resolve()
    pub = out / "public"
    pub.mkdir(parents=True, exist_ok=True)
    tl = jload(work / lang / "timeline.json")
    win = pick_window(tl)
    dur = story_duration(win)
    apath = work / lang / "audio.wav"
    voice = None
    if apath.exists():
        vw = Wav.load(apath)
        voice = Wav(vw.samples[int(win[0] * vw.sr): int(win[1] * vw.sr)], vw.sr)
    bed = load_music(music)
    audio = mix(voice, bed, dur) if (voice is not None or bed is not None) else None
    if audio is not None:
        audio.save(pub / "story_audio.wav")
    props = make_props(m, lang, dur, "story_audio.wav" if audio is not None else None)
    pp = jdump(props, out / "props.json")
    layout = None
    if render:
        subprocess.run(["node", str(ROOT / "remotion" / "render_story.mjs"), "--props", str(pp), "--public", str(pub),
                        "--out", str(out / "video.mp4"), "--audit", str(out / "layout.json")], check=True, cwd=ROOT / "remotion")
        layout = jload(out / "layout.json")
    qa = qa_story(props, Wav.load(pub / "story_audio.wav") if audio is not None else None, layout)
    qa["music"] = bed is not None
    qa["voice"] = voice is not None
    jdump(qa, out / "qa.json")
    return qa
