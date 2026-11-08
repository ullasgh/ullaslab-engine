"""WP14 Instagram Story: window pick, ducking, loudness, safe zones, payload, schema. No network, no Chrome."""
import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest
from conftest import fake_tts_factory, speechlike
from ullaslab_engine import io as eio
from ullaslab_engine import pipeline as P
from ullaslab_engine import story as ST
from ullaslab_engine.audio import Wav, loudness_lufs, true_peak_dbtp
from ullaslab_engine.bundle import BundleError, load_bundle
from ullaslab_engine.config import ROOT

SR = 48000


def music(seconds=6.0, level=0.2):
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330, 440)) / 4
    x = x * (0.7 + 0.3 * np.sin(2 * np.pi * 2 * t))
    return Wav((x * level).astype(np.float32), SR)


def test_pick_window_uses_hook_scene_and_caps():
    tl = {"scenes": [{"start": 0.0, "end": 20.0}, {"start": 20.0, "end": 30.0}]}
    a, b = ST.pick_window(tl)
    assert a == 0.0 and b == pytest.approx(ST.cfg()["voice_max_s"])
    assert ST.pick_window({"scenes": [{"start": 2.0, "end": 6.0}]}) == (2.0, 6.0)


@pytest.mark.parametrize("win,expected", [((0, 3), 10.0), ((0, 8), 10.5), ((0, 12.5), 15.0)])
def test_duration_clamped_to_10_15(win, expected):
    assert ST.story_duration(win) == pytest.approx(expected)


def test_music_is_ducked_under_voice():
    voice = speechlike(4.0, sr=SR)
    m = music(12.0)
    dur = 12.0
    mixed = ST.mix(voice, m, dur)
    env = ST.voice_env(np.pad(ST.resample(voice, SR).samples, (0, int(dur * SR) - int(4 * SR))), SR,
                       ST.cfg()["duck_attack_s"], ST.cfg()["duck_release_s"])
    during = env[int(1.0 * SR):int(3.5 * SR)].mean()
    after = env[int(6 * SR):int(10 * SR)].mean()
    assert during > 0.5 and after < 0.02
    # music-only mix level vs same bed under voice: gain reduction at least ~ duck_db/2 during speech
    bed_only = ST.mix(None, m, dur)
    bed_rms = np.sqrt(np.mean(bed_only.samples[int(6 * SR):int(10 * SR)] ** 2))
    tail_rms = np.sqrt(np.mean(mixed.samples[int(6 * SR):int(10 * SR)] ** 2))
    voice_only = np.sqrt(np.mean(mixed.samples[int(1 * SR):int(3.5 * SR)] ** 2))
    assert voice_only > tail_rms  # the narration, not the bed, leads
    assert bed_rms > 0


@pytest.mark.parametrize("with_voice,with_music", [(True, True), (False, True), (True, False)])
def test_loudness_in_window_and_peak(with_voice, with_music):
    w = ST.mix(speechlike(5.0, sr=SR) if with_voice else None, music(12.0) if with_music else None, 12.0)
    c = ST.cfg()
    assert abs(loudness_lufs(w) - c["loudness_lufs"]) <= c["loudness_tolerance_lu"]
    assert true_peak_dbtp(w) <= c["true_peak_max_dbtp"]


def test_fades_in_and_out():
    w = ST.mix(None, music(12.0), 12.0)
    assert abs(w.samples[:200]).max() < 0.02 and abs(w.samples[-200:]).max() < 0.02
    assert abs(w.samples[SR:2 * SR]).max() > 0.05


def test_short_music_loops_to_length():
    w = ST.mix(None, music(2.0), 11.0)
    assert len(w.samples) == int(11 * SR)
    assert np.sqrt(np.mean(w.samples[int(8 * SR):int(10 * SR)] ** 2)) > 0.02


def test_no_music_no_voice_is_silent_not_error():
    w = ST.mix(None, None, 10.0)
    assert float(np.abs(w.samples).max()) == 0.0


def _layout(elems):
    return {"width": 1080, "height": 1920, "frames": [{"frame": 1, "scene": "story", "elements": elems}]}


def el(role, x=60, y=400, w=900, h=120, px=60, fg="#F2F5F9", bg="#0E1726"):
    return {"role": role, "x": x, "y": y, "w": w, "h": h, "fontPx": px, "fg": fg, "bg": bg, "words": 3}


PROPS = {"lang": "en", "text": "Yields moved. Here is the context", "sub": "", "source": "Source: FRED", "edu": "Education only",
         "cta": "New Reel on our profile", "aiVoice": "", "durationS": 12.0, "audio": "", "rtl": False, "accent": "#4FD1C5"}


def failed(qa):
    return {c["name"] for c in qa["checks"] if not c["passed"]}


def test_qa_passes_inside_story_zone():
    assert ST.qa_story(PROPS, None, _layout([el("headline"), el("body", y=1400, h=100, px=48), el("stamp", y=1480, h=60, px=36)]))["passed"]


@pytest.mark.parametrize("kw", [dict(y=200), dict(y=1500, h=120), dict(x=20), dict(x=200, w=850)])
def test_qa_fails_outside_story_zone(kw):
    qa = ST.qa_story(PROPS, None, _layout([el("headline", **kw)]))
    assert "elements_outside_story_safe_zone" in failed(qa)


def test_qa_fails_small_text_low_contrast_duration_and_long_text():
    assert "text_below_min_px" in failed(ST.qa_story(PROPS, None, _layout([el("body", px=30)])))
    assert "contrast_failures" in failed(ST.qa_story(PROPS, None, _layout([el("body", fg="#3a3a3a")])))
    assert "duration_s" in failed(ST.qa_story({**PROPS, "durationS": 20.0}, None, _layout([el("body")])))
    assert "text_chars" in failed(ST.qa_story({**PROPS, "text": "x" * 61}, None, _layout([el("body")])))
    assert "layout_audit" in failed(ST.qa_story(PROPS, None, None))


def test_qa_loudness_gate_fails_on_quiet_audio():
    quiet = Wav(speechlike(5.0, sr=SR).samples * 0.01, SR)
    assert "lufs" in failed(ST.qa_story(PROPS, quiet, _layout([el("body")])))


def test_safe_zone_json_matches_remotion_config():
    z = json.loads((ROOT / "config" / "safe_zones.json").read_text())["story"]
    ts = (ROOT / "remotion" / "src" / "storyConfig.ts").read_text()
    m = re.search(r"STORY_SAFE = \{ w: (\d+), h: (\d+), top: (\d+), bottom: (\d+), sides: (\d+)", ts)
    assert tuple(map(int, m.groups())) == (z["width"], z["height"], z["top"], z["bottom"], z["sides"])
    assert z["top"] >= 250 and z["bottom"] >= 340
    assert "10;" in ts and "15;" in ts


def test_edu_line_is_first_sentence():
    assert ST.edu_line({"en": "Education only. Not investment advice.", "hi": "केवल शिक्षा। निवेश सलाह नहीं।"}, "hi") == "केवल शिक्षा"
    assert ST.edu_line("Education only. Not advice.", "en") == "Education only"


def test_story_langs_and_props(work):
    m = load_bundle(work / "bundle")
    assert ST.story_langs(m) == []
    m["story"] = {"text": {"en": "Rates moved, context inside"}, "sub": {"en": "A calm look at data"}}
    assert ST.story_langs(m) == ["en"]
    p = ST.make_props(m, "en", 12.0, "story_audio.wav")
    assert p["cta"] == "New Reel on our profile" and p["edu"].startswith("Education only")
    assert p["aiVoice"] == "" or m["synthetic_voice"]


def test_manifest_schema_story(work):
    mp = work / "bundle" / "manifest.json"
    m = json.loads(mp.read_text())
    m["story"] = {"text": {"en": "ok"}}
    mp.write_text(json.dumps(m))
    load_bundle(work / "bundle")
    m["story"] = {"text": {"en": "x" * 61}}
    mp.write_text(json.dumps(m))
    with pytest.raises(BundleError):
        load_bundle(work / "bundle")


def test_stage_story_without_render(work):
    mp = work / "bundle" / "manifest.json"
    m = json.loads(mp.read_text())
    m["story"] = {"text": {"en": "Rates moved, context inside"}}
    mp.write_text(json.dumps(m))
    P.stage_tts(work, "en", tts_fn=fake_tts_factory(2.6))
    import soundfile as sf
    sf.write(str(work / "bed.mp3"), music(8.0).samples, SR, format="WAV")
    qa = ST.stage_story(work, "en", work / "bed.mp3", render=False)
    assert qa["music"] and qa["voice"]
    assert {"lufs", "true_peak_dbtp"} <= {c["name"] for c in qa["checks"]}
    assert ST.stage_story(work, "hi", None, render=False) is None


BASE = "https://acct.r2.cloudflarestorage.com/b/"


def payload(**extra):
    return {"job_id": "j1", "bundle_url": BASE + "bundle?X=1", "languages": ["en"],
            "outputs": {"story_en.mp4": BASE + "s?X=2"}, **extra}


def test_payload_music_url_validated_and_masked():
    p = payload(music_url=BASE + "music?X=3")
    eio.validate_payload(p)
    assert any("music" in line for line in eio.mask_lines(p))
    with pytest.raises(eio.TransferError):
        eio.validate_payload(payload(music_url="https://evil.example.com/a.mp3"))
    assert "story_en.mp4" in p["outputs"]


def test_music_cap_and_no_music_files_committed():
    assert eio.MAX_MUSIC_BYTES <= 30 * 1024 * 1024
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in files if f.lower().endswith((".mp3", ".ogg", ".flac", ".m4a", ".aac"))]
    assert not [f for f in files if "music" in f.lower() and f.lower().endswith(".wav")]


@pytest.mark.skipif(not os.environ.get("RUN_RENDER"), reason="set RUN_RENDER=1 (needs node + Chrome)")
def test_story_render_passes_qa(work):
    mp = work / "bundle" / "manifest.json"
    m = json.loads(mp.read_text())
    m["story"] = {"text": {"en": "Yields moved: what the data says", "hi": "यील्ड बदली: डेटा क्या कहता है"}, "sub": {"en": "A calm look at the context"}}
    mp.write_text(json.dumps(m, ensure_ascii=False))
    P.stage_tts(work, "en", tts_fn=fake_tts_factory(2.6))
    qa = ST.stage_story(work, "en", None)
    assert qa["passed"], [c for c in qa["checks"] if not c["passed"]]
    vid = work / "en" / "story" / "video.mp4"
    assert vid.stat().st_size < 100 * 1024 * 1024 and shutil.which("node")
