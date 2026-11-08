"""Stage functions shared by the CLI, the CI workflow and the local fixture run."""
from __future__ import annotations
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import captions as cap
from .audio import Wav, normalize_loudness
from .bundle import load_bundle, seg_text
from .config import ROOT, language
from .qa import run_qa, write_qa
from .synth import natural_timeline, slot_timeline, synth_segments, SR
from .tts import NoVoiceAvailable, tts as default_tts

SRC = "en"


def jdump(obj, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def jload(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def voice_path(work: Path, m: dict) -> Path | None:
    v = work / "voice.wav"
    if v.exists():
        return v
    if m.get("voice_ref"):
        p = (work / "bundle" / m["voice_ref"]).resolve()
        if (work / "bundle").resolve() in p.parents and p.exists():
            return p
    return None


def stage_tts(work: Path, lang: str, tts_fn=default_tts, want_natural: bool = False) -> dict:
    """Synthesise every segment, build the timeline(s) and write normalised audio.
    Source language: natural master timeline. Other languages: slot-aligned to timing_en.json,
    plus a natural timeline when a variant needs it. Returns a status dict."""
    m = load_bundle(work / "bundle")
    out = work / lang
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    try:
        wavs = synth_segments(m, lang, voice_path(work, m), tts_fn)
    except NoVoiceAvailable:
        jdump({"lang": lang, "voice": False}, out / "status.json")
        return {"voice": False}
    src = m["source_lang"]
    if lang == src:
        audio, tl = natural_timeline(m, lang, wavs)
        normalize_loudness(audio).save(out / "audio.wav")
        jdump(tl, out / "timeline.json")
        jdump(tl, work / f"timing_{src}.json")
    else:
        master = jload(work / f"timing_{src}.json")
        audio, tl = slot_timeline(m, lang, wavs, master)
        normalize_loudness(audio).save(out / "audio.wav")
        jdump(tl, out / "timeline.json")
        if want_natural:
            a2, t2 = natural_timeline(m, lang, wavs)
            normalize_loudness(a2).save(out / "audio_natural.wav")
            jdump(t2, out / "timeline_natural.json")
    rtf = (time.monotonic() - t0) / max(1e-6, sum(w.duration for w in wavs))  # CPU realtime factor (feasibility item 2)
    flags = [f"seg{i}: {f}" for i, w in enumerate(wavs) for f in w.flags]  # naturalness gate failures after one retry
    jdump({"lang": lang, "voice": True, "rtf": round(rtf, 2), "naturalness_flags": flags}, out / "status.json")
    return {"voice": True, "overruns": tl.get("overruns", []), "rtf": round(rtf, 2), "naturalness_flags": flags}


def stage_captions(work: Path, lang: str, use_asr: bool = True) -> dict:
    """SRT/VTT on the master timeline for every language; cues.json for burned-in captions.
    English master: word timing refined by faster-whisper. Others: segment mapping (no ASR)."""
    m = load_bundle(work / "bundle")
    src = m["source_lang"]
    master = jload(work / f"timing_{src}.json")
    out = work / lang
    out.mkdir(parents=True, exist_ok=True)
    asr_words = None
    if lang == src and use_asr and (out / "audio.wav").exists():
        from .asr import transcribe, words_by_segment
        asr_words = words_by_segment(transcribe(out / "audio.wav", lang), master)
    windows = {s["id"]: (s["start"], s["end"]) for s in master["segments"]}
    cues = cap.build_cues(m, lang, windows, asr_words)
    (out / "captions.srt").write_text(cap.to_srt(cues), encoding="utf-8")
    (out / "captions.vtt").write_text(cap.to_vtt(cues), encoding="utf-8")
    jdump(cues, out / "cues.json")
    if (out / "timeline_natural.json").exists():  # captions for the dubbed visual variant
        nt = jload(out / "timeline_natural.json")
        w2 = {s["id"]: (s["start"], s["end"]) for s in nt["segments"]}
        jdump(cap.build_cues(m, lang, w2, None), out / "cues_natural.json")
    return {"cues": len(cues)}


def make_props(work: Path, lang: str, orientation: str, natural: bool) -> dict:
    """Remotion input props. Content stays on the runner; this file is never uploaded."""
    m = load_bundle(work / "bundle")
    out = work / lang
    tl = jload(out / ("timeline_natural.json" if natural else "timeline.json"))
    cues = jload(out / ("cues_natural.json" if natural else "cues.json"))
    texts = {s["id"]: seg_text(m, s, lang) for s in m["segments"]}
    return {
        "lang": lang, "orientation": orientation, "format": m["format"], "template": m.get("template", ""),
        "hookStyle": m.get("hook_style", ""), "disclaimer": m["disclaimer"],
        "scenes": m["scenes"], "timeline": tl, "cues": cues, "segmentWords": {k: len(v.split()) for k, v in texts.items()},
        "audio": "audio.wav",
        "numberLocale": "en-IN" if language(lang)["number_format"] == "indian" else "en-US",
        "rtl": lang == "ar",
    }


def stage_render(work: Path, lang: str, name: str, orientation: str, natural: bool = False) -> Path:
    """Render one MP4 (+ layout audit JSON) with Remotion. Returns the mp4 path."""
    out = (work / lang / name).resolve()
    pub = out / "public"
    pub.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / lang / ("audio_natural.wav" if natural else "audio.wav"), pub / "audio.wav")
    props = jdump(make_props(work, lang, orientation, natural), out / "props.json")
    subprocess.run(["node", str(ROOT / "remotion" / "render.mjs"), "--props", str(props), "--public", str(pub),
                    "--out", str(out / "video.mp4"), "--audit", str(out / "layout.json")], check=True, cwd=ROOT / "remotion")
    return out / "video.mp4"


def stage_qa(work: Path, lang: str, name: str | None, orientation: str, natural: bool = False,
             use_asr: bool = True, master_total: float | None = None) -> dict:
    """Run gates and write qa.json (numbers only). name=None means an audio-only dub track."""
    m = load_bundle(work / "bundle")
    d = work / lang
    audio_path = d / ("audio_natural.wav" if natural else "audio.wav")
    tl = jload(d / ("timeline_natural.json" if natural else "timeline.json"))
    cues = jload(d / ("cues_natural.json" if natural else "cues.json"))
    wav = Wav.load(audio_path)
    err = None
    if use_asr:
        from .asr import error_rate, transcribe
        hyp = cap.joiner(lang).join(w[0] for w in transcribe(audio_path, lang))
        ref = cap.joiner(lang).join(seg_text(m, s, lang) for s in m["segments"])
        err = error_rate(ref, hyp, lang)
    if name:
        layout = jload(d / name / "layout.json")
    else:
        sz = json.loads((ROOT / "config" / "safe_zones.json").read_text())[orientation]
        layout = {"width": sz["width"], "height": sz["height"], "frames": []}
    qa = run_qa(m, lang, wav, tl, cues, layout, err, orientation, master_total)
    qa["variant"] = name
    write_qa(qa, (d / name / "qa.json") if name else (d / "qa.json"))
    return qa
