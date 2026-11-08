import json
import numpy as np
from conftest import fake_tts_factory, speechlike
from ullaslab_engine import pipeline as P
from ullaslab_engine.audio import Wav, loudness_lufs, true_peak_dbtp
from ullaslab_engine.bundle import load_bundle
from ullaslab_engine.synth import beats_for, natural_timeline, slot_timeline, synth_segments


def test_beats_never_more_than_4s_apart():
    for dur in (2.0, 7.3, 12.0):
        b = beats_for(10.0, 10.0 + dur)
        pts = b + [10.0 + dur]
        assert b[0] == 10.0 and all(y - x <= 4.0 for x, y in zip(pts, pts[1:]))


def test_natural_timeline_scenes_are_contiguous(bundle_dir):
    m = load_bundle(bundle_dir)
    wavs = synth_segments(m, "en", None, fake_tts_factory())
    audio, tl = natural_timeline(m, "en", wavs)
    sc = tl["scenes"]
    assert sc[0]["start"] == 0 and all(a["end"] == b["start"] for a, b in zip(sc, sc[1:]))
    assert abs(audio.duration - tl["total_s"]) < 0.01
    assert sc[-1]["kind"] == "disclaimer"


def test_disclaimer_card_appended_when_manifest_has_none(bundle_dir):
    m = load_bundle(bundle_dir)
    m["scenes"] = m["scenes"][:-1]
    m["segments"] = m["segments"][:-1]
    _, tl = natural_timeline(m, "en", synth_segments(m, "en", None, fake_tts_factory()))
    assert tl["scenes"][-1]["kind"] == "disclaimer" and tl["scenes"][-1]["end"] - tl["scenes"][-1]["start"] == 3.0


def test_slot_timeline_flags_overrun(bundle_dir):
    m = load_bundle(bundle_dir)
    for seg in m["segments"]:
        seg["text"]["hi"] = seg["text"]["en"]  # same length, so only the speaking rate differs
    master = natural_timeline(m, "en", synth_segments(m, "en", None, fake_tts_factory(2.6)))[1]
    ok_audio, ok = slot_timeline(m, "hi", synth_segments(m, "hi", None, fake_tts_factory(2.6)), master)
    assert ok["overruns"] == [] and abs(ok_audio.duration - master["total_s"]) < 0.01
    _, bad = slot_timeline(m, "hi", synth_segments(m, "hi", None, fake_tts_factory(1.0)), master)  # 2.6x slower speech
    assert bad["overruns"]


def test_stage_flow_en_then_dub_with_fake_tts(work):
    fake = fake_tts_factory()
    m = load_bundle(work / "bundle")
    for s in m["segments"]:
        s["text"]["hi"] = "यह एक कृत्रिम परीक्षण वाक्य है जो केवल जाँच के लिए है"
    (work / "bundle" / "manifest.json").write_text(json.dumps({k: v for k, v in m.items()} | {
        "scenes": [{kk: vv for kk, vv in sc.items() if kk != "chart_data"} for sc in m["scenes"]]}))
    r = P.stage_tts(work, "en", tts_fn=fake)
    assert r["voice"] and (work / "en" / "audio.wav").exists() and (work / "timing_en.json").exists()
    w = Wav.load(work / "en" / "audio.wav")
    assert abs(loudness_lufs(w) + 14) <= 1 and true_peak_dbtp(w) <= -1
    P.stage_tts(work, "hi", tts_fn=fake, want_natural=True)
    assert (work / "hi" / "timeline_natural.json").exists()
    P.stage_captions(work, "en", use_asr=False)
    P.stage_captions(work, "hi", use_asr=False)
    assert (work / "hi" / "captions.srt").read_text().startswith("1\n")
    assert (work / "hi" / "cues_natural.json").exists()
    qa = P.stage_qa(work, "hi", None, "vertical", use_asr=False, master_total=json.loads((work / "timing_en.json").read_text())["total_s"])
    assert "A5" in qa["gates"]
    p = P.make_props(work, "hi", "vertical", natural=True)
    assert p["numberLocale"] == "en-IN" and p["rtl"] is False
    assert "headline" not in json.dumps(p["timeline"])


def test_no_voice_marks_captions_only(work, monkeypatch):
    from ullaslab_engine.tts import NoVoiceAvailable

    def boom(*a, **k):
        raise NoVoiceAvailable("x")
    assert P.stage_tts(work, "en", tts_fn=boom) == {"voice": False}
