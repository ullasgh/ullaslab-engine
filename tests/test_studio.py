"""WP4 studio tests: alignment, scene timing, ffmpeg graph builders, loudness, packaging, resumability.
The real-render end-to-end (say + mlx-whisper + Remotion) runs only with RUN_STUDIO_E2E=1."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from studio_fixture import NARRATION, make_item, scenes_doc, make_clip
from conftest import speechlike
from ullaslab_engine.config import ROOT
from ullaslab_engine.studio import audio as A, pack as K
from ullaslab_engine.studio.assemble import AssembleError, build_props, to_kit_chart
from ullaslab_engine.studio.captions import build_cues, cues_to_srt
from ullaslab_engine.studio.run import Studio, check_spec
from ullaslab_engine.studio.timings import CoverageError, align, frame_ranges, norm_tokens, time_output, transcribe_words

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


def fake_asr_words(text: str, wps: float = 2.6, start: float = 0.3):
    out, t = [], start
    for w in text.split():
        d = max(0.15, len(w) * 0.06)
        out.append((w, t, t + d))
        t += d + 0.08
    return out


# ---------------------------------------------------------------- alignment
def test_norm_tokens_numbers_and_punctuation():
    assert norm_tokens("5.25%") == ["five", "point", "two", "five", "percent"]
    assert norm_tokens("Texas?") == ["texas"]
    assert norm_tokens("1,200") == ["one", "thousand", "two", "hundred"]
    assert norm_tokens("don’t") == ["dont"]


def test_align_spoken_numbers_match_digits():
    script = "Rates rose to 5.25% in July".split()
    asr = [("Rates", 0, .3), ("rose", .3, .6), ("to", .6, .7), ("five", .7, .9), ("point", .9, 1.0), ("two", 1.0, 1.1), ("five", 1.1, 1.3),
           ("percent", 1.3, 1.7), ("in", 1.7, 1.8), ("July", 1.8, 2.2)]
    a = align(script, asr)
    assert a.coverage == 1.0
    assert a.times[3] == (0.7, 1.7)       # the printed number spans all of its spoken tokens


def test_align_fuzzy_match_and_interpolation():
    script = "The Treasury yield climbed sharply yesterday".split()
    asr = [("the", 0, .2), ("treasury", .2, .8), ("yeild", .8, 1.1), ("climbed", 1.1, 1.6), ("sharply", 1.6, 2.0), ("yesterday", 2.0, 2.6)]
    a = align(script, asr)
    assert a.coverage == 1.0              # 'yeild' fuzzy-matched to 'yield'
    asr2 = asr[:2] + asr[3:]              # ASR dropped a word: it is interpolated, not lost
    a2 = align(script, asr2)
    assert a2.coverage < 1.0 and a2.matched.count(False) == 1
    s, e = a2.times[2]
    assert asr2[1][2] - 1e-6 <= s < e <= asr2[2][1] + 1e-6


def test_times_monotonic_and_positive():
    words = NARRATION[1].split()
    a = align(words, fake_asr_words(NARRATION[1])[::2])
    starts = [t[0] for t in a.times]
    assert starts == sorted(starts) and all(e > s for s, e in a.times)


def test_time_output_fills_schema_fields_and_is_contiguous():
    doc = scenes_doc()
    o = doc["outputs"][0]
    stats = time_output(o["scenes"], fake_asr_words(" ".join(NARRATION)), 20.0, "long")
    assert stats["coverage"] >= 0.95
    sc = o["scenes"]
    assert sc[0]["narration"]["start_s"] == 0.0
    for a, b in zip(sc, sc[1:]):
        assert a["narration"]["end_s"] == b["narration"]["start_s"]
    assert sc[-1]["narration"]["end_s"] >= sc[-1]["narration"]["words"][-1]["end"]
    assert all(w["end"] >= w["start"] for s in sc for w in s["narration"]["words"])
    jsonschema.validate(doc, json.loads((ROOT / "tests/fixtures/scenes/scenes.schema.json").read_text()))   # still schema-valid
    fr = frame_ranges(sc)
    assert fr[0][0] == 0 and all(fr[i][1] == fr[i + 1][0] for i in range(3))
    assert fr[-1][1] == round(sc[-1]["narration"]["end_s"] * 30)


def test_low_coverage_fails_loudly():
    o = scenes_doc()["outputs"][0]
    asr = fake_asr_words("completely different words that never occur in the script at all")
    with pytest.raises(CoverageError, match="coverage"):
        time_output(o["scenes"], asr, 10.0, "long")


def test_backend_selection(monkeypatch):
    import ullaslab_engine.studio.timings as T
    monkeypatch.setattr(T, "mlx_available", lambda: True)
    monkeypatch.setattr(T, "transcribe_mlx", lambda p, l: [("a", 0, 1)])
    monkeypatch.setattr(T, "transcribe_faster", lambda p, l: [("b", 0, 1)])
    assert transcribe_words(Path("x"), "en") == ([("a", 0, 1)], "mlx")
    monkeypatch.setattr(T, "mlx_available", lambda: False)
    assert transcribe_words(Path("x"), "en") == ([("b", 0, 1)], "faster")
    assert transcribe_words(Path("x"), "en", "mlx")[1] == "mlx"


# ---------------------------------------------------------------- captions
def timed_doc():
    doc = scenes_doc()
    for o in doc["outputs"]:
        time_output(o["scenes"], fake_asr_words(" ".join(NARRATION)), 22.0, o["output"])
    return doc


def test_cues_limits_and_srt():
    cues = build_cues(timed_doc()["outputs"][0]["scenes"])
    assert cues and all(len(c["lines"]) <= 2 for c in cues)
    assert all(len(" ".join(w["w"] for w in ln)) <= 34 for c in cues for ln in c["lines"])
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(cues, cues[1:]))
    srt = cues_to_srt(cues)
    assert srt.startswith("1\n00:00:") and " --> " in srt


# ---------------------------------------------------------------- assembly
def test_chart_conversion_and_unresolved_spec_error():
    c = to_kit_chart("c1", {"type": "line", "title": "T", "unit": "%", "series": [{"name": "s", "points": [{"x": "a", "y": 1}, {"x": "b", "y": 2}]}],
                            "source": {"name": "FRED", "as_of": "2026-11"}, "freshness": "RECENT"})
    assert c["kind"] == "line" and c["meta"]["source"]["name"] == "FRED" and c["meta"]["period"] == "a to b"
    with pytest.raises(AssembleError, match="unresolved fetch spec"):
        to_kit_chart("c1", {"source": "worldbank", "args": {"country": "IND"}})


def test_build_props_resolves_each_scene_type(tmp_path):
    item = make_item(tmp_path, voice=False)
    doc = timed_doc()
    pub = tmp_path / "pub"
    clips = []
    props, warns = build_props(item, doc, doc["outputs"][0], pub, clip_prep=lambda s, d, secs, w, h: clips.append((d.name, round(secs), w, h)))
    refs = props["refs"]
    assert props["orientation"] == "horizontal" and props["width"] == 1920
    assert refs["c1"]["kind"] == "line" and refs["footage:s02"]["src"] == "footage/long/s02.mp4" and refs["auto:s04"]["meta"]
    assert clips[0][0] == "s02.mp4" and clips[0][2:] == (1920, 1080)
    assert props["durationInFrames"] == round(doc["outputs"][0]["scenes"][-1]["narration"]["end_s"] * 30)
    p2, _ = build_props(item, doc, doc["outputs"][1], pub, clip_prep=lambda *a: None)
    assert p2["orientation"] == "vertical" and p2["height"] == 1920
    assert props["captions"]


def test_missing_footage_fails_unless_preview(tmp_path):
    item = make_item(tmp_path, voice=False)
    (item / "assets.json").unlink()
    doc = timed_doc()
    with pytest.raises(AssembleError, match="no footage"):
        build_props(item, doc, doc["outputs"][0], tmp_path / "p")
    props, warns = build_props(item, doc, doc["outputs"][0], tmp_path / "p", allow_placeholder=True)
    assert warns and props["refs"]["footage:s02"]["credit"] == ""


# ---------------------------------------------------------------- audio graphs
def test_mix_graph_ducks_music_under_narration():
    g = A.mix_graph()
    assert "sidechaincompress" not in g and "amix=inputs=3:normalize=0" in g     # the duck is an upstream envelope (apply_duck)


def _voice_with_pauses(sr=48000):
    """12 s: speech 0-4, pause 4-6 (2 s), speech 6-8, pause 8-8.5 (short), speech 8.5-10.5, then silence (outro)."""
    t = np.arange(12 * sr) / sr
    v = 0.2 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    for a, b in ((4, 6), (8, 8.5), (10.5, 12)):
        v[int(a * sr):int(b * sr)] = 0
    v[: int(0.6 * sr)] = 0
    return v.astype(np.float32), t


def test_duck_music_about_20db_under_voice_with_gentle_rise_only_in_long_pauses():
    sr = 48000
    v, t = _voice_with_pauses(sr)
    m = (0.3 * np.sin(2 * np.pi * 261 * t) + 0.2 * np.sin(2 * np.pi * 392 * t)).astype(np.float32)
    g, info = A.duck_gain_db(v, m, sr, A.mix_cfg())
    gain = lambda a, b: g[int(a * 100):int(b * 100)].mean()
    rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)))
    speech = slice(int(1.0 * sr), int(3.8 * sr))
    gap = rms(v[speech]) - (rms(m[speech]) + gain(1.0, 3.8))
    assert gap >= 17.0, gap                                    # music at least about 20 dB under the voice while speaking
    assert gain(5.0, 5.9) > gain(1.0, 3.8) + 5                 # rises in the 2 s pause
    assert abs(gain(8.1, 8.4) - gain(7.0, 7.8)) < 1.5          # 0.5 s pause is bridged, stays ducked
    assert gain(11.0, 12.0) > gain(9.0, 10.3) + 3              # outro rise
    assert np.abs(np.diff(g)).max() < 0.8                      # smooth: no step larger than 0.8 dB per 10 ms
    assert info["base_gain_db"] < 0


def test_mix_levels_exposed_in_config():
    from ullaslab_engine.config import quality
    q = quality()["MIX"]
    assert q["music_below_voice_db"] >= 20 and q["rise_db"] > 0 and q["pause_min_s"] == 1.0 and q["lufs"] == -14 and q["true_peak_max_dbtp"] <= -1


def test_loudnorm_filters_two_pass():
    p1 = A.loudnorm_filter()
    assert "I=-14.0" in p1 and "TP=-1.5" in p1 and "print_format=json" in p1 and "measured_I" not in p1
    p2 = A.loudnorm_filter({"input_i": "-20.1", "input_tp": "-3.0", "input_lra": "5.0", "input_thresh": "-30.0", "target_offset": "0.2"})
    assert "measured_I=-20.1" in p2 and "linear=true" in p2 and "offset=0.2" in p2
    assert A.parse_loudnorm_json('noise\n{\n "input_i" : "-20.0"\n}\n')["input_i"] == "-20.0"


def test_sfx_events_follow_scenes_json():
    ev = A.sfx_events(timed_doc()["outputs"][0]["scenes"])
    assert [n for n, _ in ev] == ["whoosh", "tick", "riser"]          # 'none' on the hook is skipped
    starts = {n: t for n, t in ev}
    sc = timed_doc()["outputs"][0]["scenes"]
    assert starts["whoosh"] == pytest.approx(sc[1]["narration"]["start_s"], abs=0.05)
    assert starts["riser"] == pytest.approx(sc[3]["narration"]["start_s"] - 1.4, abs=0.05)   # riser leads into the cut
    cmd = A.sfx_stem_cmd(ev, {n: Path(f"/x/{n}.wav") for n in A.SFX}, 20.0, Path("out.wav"))
    j = " ".join(cmd)
    assert "adelay=" in j and "amix=inputs=4:normalize=0" in j and cmd[-1] == "out.wav"


def test_music_licence_gate(tmp_path):
    good = {"id": "t1", "file": "a.mp3", "title": "T", "artist": "A", "source": "pixabay", "licence": "Pixabay Content Licence",
            "licence_url": "https://pixabay.com/service/license-summary/", "source_url": "https://pixabay.com/music/x", "downloaded": "2026-11-09"}
    A.check_track(good)
    for bad in ({**good, "licence": ""}, {**good, "source": "YouTube Audio Library"}, {**good, "source": "freemusicsite"},
                {**good, "source_url": "https://studio.youtube.com/channel/x/music (YouTube Audio Library)"}):
        with pytest.raises(A.AudioError):
            A.check_track(bad)
    (tmp_path / "a.mp3").write_bytes(b"x")
    assert A.pick_track([good], music_dir=tmp_path)["id"] == "t1"
    assert A.pick_track([good], music_dir=tmp_path / "none") is None


@needs_ffmpeg
def test_real_mix_hits_minus14_lufs_and_true_peak(tmp_path):
    from ullaslab_engine.audio import Wav
    nar = tmp_path / "nar.wav"
    speechlike(8.0, 48000, level=0.2).save(nar)
    lib = A.make_sfx_library(tmp_path / "sfx")
    ev = [("whoosh", 1.0), ("hit", 4.0)]
    A.run(A.narration_stem_cmd(nar, 9.0, tmp_path / "n.wav"), "n")
    A.run(A.sfx_stem_cmd(ev, lib, 9.0, tmp_path / "s.wav"), "s")
    A.generate_pad(tmp_path / "pad.wav", 9.0)
    A.run(A.music_stem_cmd(tmp_path / "pad.wav", 9.0, tmp_path / "m.wav"), "m")
    A.apply_duck(tmp_path / "n.wav", tmp_path / "m.wav", tmp_path / "md.wav")
    A.run(A.mix_cmd(tmp_path / "n.wav", tmp_path / "md.wav", tmp_path / "s.wav", tmp_path / "mix.wav"), "mix")
    A.loudnorm_two_pass(tmp_path / "mix.wav", tmp_path / "master.wav")
    m = A.measure(tmp_path / "master.wav")
    assert abs(m["lufs"] + 14.0) <= 0.6 and m["true_peak_dbtp"] <= -1.0
    for stem in ("n", "m", "s"):
        assert (tmp_path / f"{stem}.wav").is_file()      # stems stay separate files
    import re

    def lufs(f, ss, t):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(ss), "-t", str(t), "-i", str(f), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
        return float(re.search(r"I:\s+(-?[\d.]+) LUFS", r[r.rindex("Summary:"):]).group(1))
    assert lufs(tmp_path / "n.wav", 1.5, 5.0) - lufs(tmp_path / "md.wav", 1.5, 5.0) >= 18.5     # voice vs bed on the stems while narrating


@needs_ffmpeg
def test_music_is_ducked_while_narration_speaks(tmp_path):
    import soundfile as sf
    sp = speechlike(4.0, 48000, level=0.3).samples
    nar = np.concatenate([sp, np.zeros(48000 * 4, dtype=np.float32)])        # speech 0-4 s, silence 4-8 s
    sf.write(str(tmp_path / "n.wav"), nar, 48000)
    tt = np.arange(8 * 48000) / 48000
    sf.write(str(tmp_path / "m.wav"), (0.2 * np.sin(2 * np.pi * 330 * tt)).astype(np.float32), 48000)     # steady bed
    A.apply_duck(tmp_path / "n.wav", tmp_path / "m.wav", tmp_path / "duck.wav")
    d, sr = sf.read(str(tmp_path / "duck.wav"))
    d = d if d.ndim == 1 else d.mean(axis=1)
    rms = lambda x, a, b: float(np.sqrt(np.mean(x[int(a * sr):int(b * sr)] ** 2)))
    assert rms(d, 1.5, 3.5) < 0.5 * rms(d, 6.0, 7.5)           # bed at least ~6 dB lower under speech than in the long pause
    assert 20 * np.log10(rms(nar, 1.5, 3.5) / rms(d, 1.5, 3.5)) >= 19      # voice to music gap while speaking


# ---------------------------------------------------------------- packaging
def test_finals_are_versioned_never_overwritten(tmp_path):
    src = tmp_path / "w.mp4"
    src.write_bytes(b"1")
    a = K.publish_file(src, tmp_path, "long", ".mp4")
    src.write_bytes(b"2")
    b = K.publish_file(src, tmp_path, "long", ".mp4")
    src.write_bytes(b"3")
    c = K.publish_file(src, tmp_path, "long", ".mp4")
    assert [p.name for p in (a, b, c)] == ["long.mp4", "long.v2.mp4", "long.v3.mp4"]
    assert a.read_bytes() == b"1" and b.read_bytes() == b"2"


def test_merge_assets_md_is_idempotent(tmp_path):
    (tmp_path / "assets.md").write_text("# Asset ledger\n\n| File |\n")
    audio = {"long": {"music": {"title": "T", "artist": "A", "source": "pixabay", "source_url": "u", "licence": "L", "licence_url": "https://l"}, "sfx": ["tick"]}}
    K.merge_assets_md(tmp_path, audio)
    K.merge_assets_md(tmp_path, audio)
    t = (tmp_path / "assets.md").read_text()
    assert t.count("## Audio ledger") == 1 and "| File |" in t and "tick" in t


def test_cost_and_publish_pack(tmp_path):
    item = make_item(tmp_path, voice=False)
    assert "Total spend: $0.00" in K.cost_md(item, {})
    audio = {"long": {"music": {"title": "T", "artist": "A", "licence": "CC0"}, "sfx": []}}
    t = K.publishing_pack(item, timed_doc(), {"title": "My title"}, [], audio)
    assert t.index(K.DISCLAIMER) < t.index("Credits") and "My title" in t and "containsSyntheticMedia" in t and "#economy" in t and "#economics" in t and "macro" not in t.lower()


# ---------------------------------------------------------------- resumability (fake ASR + fake renderer, real ffmpeg)
def fake_render(props: Path, public: Path, out: Path, *, comp="StudioVideo", scale=1.0, frame=None):
    p = json.loads(props.read_text())
    if frame is not None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x203040:s=1280x720", "-frames:v", "1", str(out)], check=True)
        return
    w, h = int(p["width"] * scale), int(p["height"] * scale)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x203040:s={w}x{h}:r=30:d={p['durationInFrames'] / 30:.3f}",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", str(out)], check=True)


@pytest.fixture
def studio_item(tmp_path):
    item = make_item(tmp_path, voice=False)
    speechlike(20.0, 24000, level=0.2).save(item / "voice.wav")
    return item


@needs_ffmpeg
def test_studio_resumes_and_versions(studio_item):
    calls = {"asr": 0, "render": 0}

    def asr(p, lang):
        calls["asr"] += 1
        return fake_asr_words(" ".join(NARRATION)), "fake"

    def render(*a, **k):
        calls["render"] += 1
        return fake_render(*a, **k)
    logs = []
    mk = lambda **kw: Studio(studio_item, asr=asr, render=render, log=logs.append, **kw)
    s1 = mk(preview=True)
    s1.run()
    assert s1.ran == ["timings", "broll", "assemble", "render", "mix"]
    assert calls["asr"] == 1                                   # one voice file, transcribed once for 3 outputs
    for o in ("long", "short", "reel"):
        assert (studio_item / "preview" / f"{o}.mp4").is_file()
    assert check_spec(studio_item / "preview" / "long.mp4", 960, 540) == []
    r1 = calls["render"]
    s2 = mk(preview=True)
    s2.run()
    assert s2.ran == [] and calls["render"] == r1             # every stage skipped from checkpoints
    # a fresh object resumes after a partial run: delete the mix checkpoint's output only
    (studio_item / "work" / "preview" / "audio.json").unlink()
    s3 = mk(preview=True)
    s3.run()
    assert s3.ran == ["mix"] and calls["render"] == r1         # render not repeated
    # final run reuses timings/broll, versions finals
    f1 = mk()
    f1.run()
    assert "timings" not in f1.ran and "broll" not in f1.ran and f1.ran[-1] == "package"
    first = studio_item / "long.mp4"
    assert first.is_file() and (studio_item / "thumb.png").is_file() and (studio_item / "captions.long.srt").is_file()
    assert check_spec(first, 1920, 1080) == [] and check_spec(studio_item / "reel.mp4", 1080, 1920) == []
    for n in ("cost.md", "assets.md", "publish.md"):
        assert (studio_item / n).is_file()
    assert "Audio ledger" in (studio_item / "assets.md").read_text()
    size = first.stat().st_size
    f2 = mk(force=True)
    f2.run()
    assert (studio_item / "long.v2.mp4").is_file() and first.stat().st_size == size   # earlier final untouched


@needs_ffmpeg
def test_changed_scenes_invalidate_checkpoints(studio_item):
    asr = lambda p, lang: (fake_asr_words(" ".join(NARRATION)), "fake")
    s = Studio(studio_item, preview=True, asr=asr, render=fake_render, log=lambda m: None)
    s.run(until="timings")
    d = json.loads((studio_item / "scenes.json").read_text())
    d["outputs"][0]["scenes"][0]["narration"]["text"] += " today"
    (studio_item / "scenes.json").write_text(json.dumps(d))
    s2 = Studio(studio_item, preview=True, asr=asr, render=fake_render, log=lambda m: None)
    s2.run(until="timings")
    assert s2.ran == ["timings"]


@needs_ffmpeg
def test_coverage_failure_stops_pipeline(studio_item):
    s = Studio(studio_item, preview=True, asr=lambda p, l: (fake_asr_words("nothing matches here whatsoever"), "fake"), render=fake_render, log=lambda m: None)
    with pytest.raises(CoverageError):
        s.run()
    assert not (studio_item / "work" / "scenes.timed.json").exists()


# ---------------------------------------------------------------- real end to end (macOS, mlx-whisper, Remotion)
@pytest.mark.skipif(not os.environ.get("RUN_STUDIO_E2E"), reason="set RUN_STUDIO_E2E=1 (needs say, mlx-whisper, node)")
def test_e2e_preview_all_three_outputs(tmp_path):
    item = make_item(tmp_path)
    s = Studio(item, preview=True, log=lambda m: None)
    s.run()
    for o, (w, h) in {"long": (960, 540), "short": (540, 960), "reel": (540, 960)}.items():
        assert check_spec(item / "preview" / f"{o}.mp4", w, h) == []


# ---------------------------------------------------------------- caption layout (long, short, reel)
@pytest.mark.parametrize("output,orientation", [("long", "horizontal"), ("short", "vertical"), ("reel", "vertical")])
def test_captions_inside_safe_area_and_clear_of_content(output, orientation):
    from ullaslab_engine.studio import layout_check as LC
    doc = timed_doc()
    o = next(x for x in doc["outputs"] if x["output"] == output)
    assert LC.check(orientation, build_cues(o["scenes"])) == []
    b = LC.caption_boxes(orientation)
    assert b["caption"][1] >= b["content"][3] and b["content"][3] < b["safe"][3]


def test_unspaced_language_is_refused_clearly(studio_item):
    from ullaslab_engine.studio.run import StudioError
    with pytest.raises(StudioError, match="without spaces"):
        Studio(studio_item, lang="ja", asr=lambda p, l: ([], "x"), log=lambda m: None).run(until="timings")
    with pytest.raises(CoverageError, match="without spaces"):
        time_output(scenes_doc()["outputs"][0]["scenes"], fake_asr_words("zzz qqq"), 5.0, "long", lang="ja")


def test_publish_pack_drops_banned_brand_word(tmp_path):
    item = make_item(tmp_path, voice=False)
    audio = {"long": {"music": {"title": "T", "artist": "A", "licence": "CC0"}, "sfx": []}}
    t = K.publishing_pack(item, timed_doc(), {"title": "A macro view", "title_options": ["Macroeconomics 101", "Rates explained"],
                                              "hashtags": ["#macro", "#rates"]}, [], audio)
    assert "macro" not in t.lower() and "Rates explained" in t and "#rates" in t


# ---------------------------------------------------------------- end line (owner decision 2026-11-09)
def test_end_line_13_languages_and_brand_sync():
    import re
    from ullaslab_engine import endline as E
    assert len(E.END_LINES) == 13 and E.END_LINES["en"] == "Follow UllasLab. Education only."
    assert all("UllasLab" in v and "macro" not in v.lower() for v in E.END_LINES.values())
    ts = (ROOT / "remotion/src/brand.ts").read_text(encoding="utf-8")
    for lang, line in E.END_LINES.items():
        assert re.search(rf'\b{lang}: "{re.escape(line)}"', ts), lang
    assert E.end_parts("en") == ["Follow UllasLab.", "Education only."] and len(E.end_parts("hi")) == 2
    assert E.ends_with_end_line("so that is it. Follow UllasLab. Education only.", "en")
    assert not E.ends_with_end_line("Education only. Not investment advice.", "en")


def test_props_carry_end_card_over_last_seconds(tmp_path):
    doc = timed_doc()
    o = doc["outputs"][0]
    assert o["scenes"][-1]["narration"]["text"].endswith("Follow UllasLab. Education only.")
    item = make_item(tmp_path, voice=False)
    props, _ = build_props(item, doc, o, tmp_path / "p", allow_placeholder=True)
    ec, total = props["endCard"], props["durationInFrames"]
    assert ec["fromFrame"] + ec["durationInFrames"] == total and 1 <= ec["durationInFrames"] <= 90 + 1


def test_pack_description_and_caption_start_with_full_disclaimer(tmp_path):
    item = make_item(tmp_path, voice=False)
    t = K.publishing_pack(item, timed_doc(), {"title": "My title"}, [], {"long": {"music": {"title": "T", "artist": "A", "licence": "CC0"}, "sfx": []}})
    for head in ("## Description (long)", "## Caption (Instagram Reel / YouTube Short)"):
        assert t.split(head)[1].split("\n")[2] == K.DISCLAIMER
    assert "tag RECENT" not in t and "tag INFERRED" not in t


def test_music_ledger_sha256_is_verified_when_present(tmp_path):
    good = {"id": "t1", "file": "a.mp3", "title": "T", "artist": "A", "source": "pixabay", "licence": "Pixabay Content Licence",
            "licence_url": "https://pixabay.com/service/license-summary/", "source_url": "https://pixabay.com/music/x", "downloaded": "2026-11-09",
            "sha256": __import__("hashlib").sha256(b"x").hexdigest()}
    (tmp_path / "a.mp3").write_bytes(b"x")
    assert A.pick_track([good], music_dir=tmp_path)["id"] == "t1"
    (tmp_path / "a.mp3").write_bytes(b"y")
    with pytest.raises(A.AudioError, match="sha256"):
        A.pick_track([good], music_dir=tmp_path)
    with pytest.raises(A.AudioError):
        A.check_track({**good, "sha256": "zz"})


def test_real_music_ledger_is_valid_and_preferred_over_the_generated_pad(tmp_path):
    ledger = A.load_music_ledger()
    assert len(ledger) >= 3 and len({t["id"] for t in ledger}) == len(ledger)
    for t in ledger:
        A.check_track(t)
        assert isinstance(t["downloaded"], str)   # a bare YAML date is not JSON-serialisable in the studio provenance
        assert t["source"] == "pixabay" and t["licence"] == "Pixabay Content License" and t["sha256"]
        assert t["file"] == Path(t["file"]).name and t["file"].endswith(".mp3")
        local = A.MUSIC_DIR / t["file"]
        if local.is_file():                                    # audio is git-ignored; verify it when the owner's copy is present
            assert __import__("hashlib").sha256(local.read_bytes()).hexdigest() == t["sha256"]
    # with the files present (stand-ins, sha dropped) the first ledger track is chosen, never None (which means: use the pad)
    for t in ledger:
        (tmp_path / t["file"]).write_bytes(b"stub")
    stub = [{k: v for k, v in t.items() if k != "sha256"} for t in ledger]
    assert A.pick_track(stub, music_dir=tmp_path)["id"] == ledger[0]["id"]
    assert A.pick_track(stub, mood="no-such-mood", music_dir=tmp_path)["id"] == ledger[0]["id"]
    assert A.pick_track(stub, music_dir=tmp_path / "absent") is None     # only then does the studio fall back to the CC0 pad
    assert A.mix_cfg()["music_below_voice_db"] >= 20                     # ducking target unchanged


# ---------------------------------------------------------------- private R2 music fetch (mocked, no network)
def _r2_track(tmp_path, data=b"abc"):
    import hashlib
    return {"id": "t1", "file": "a.mp3", "title": "T", "artist": "A", "source": "pixabay", "licence": "L", "licence_url": "u",
            "source_url": "u", "downloaded": "2026-11-09", "sha256": hashlib.sha256(data).hexdigest()}


def test_fetch_missing_track_verifies_sha_and_installs(tmp_path):
    t = _r2_track(tmp_path)
    calls = []

    def getter(key, dst, env):
        calls.append(key)
        dst.write_bytes(b"abc")
    out = A.fetch_missing_tracks([t], tmp_path, env={}, getter=getter)
    assert out == {"fetched": ["t1"], "failed": {}} and calls == ["assets/music/a.mp3"]
    assert (tmp_path / "a.mp3").read_bytes() == b"abc"
    assert A.fetch_missing_tracks([t], tmp_path, env={}, getter=lambda *a: 1 / 0)["fetched"] == []   # present: no fetch


def test_fetch_sha_mismatch_and_errors_are_reported_not_installed(tmp_path):
    t = _r2_track(tmp_path)
    out = A.fetch_missing_tracks([t], tmp_path, env={}, getter=lambda k, d, e: d.write_bytes(b"tampered"))
    assert "sha256" in out["failed"]["t1"] and not (tmp_path / "a.mp3").exists()

    def boom(k, d, e):
        raise RuntimeError("no creds")
    out = A.fetch_missing_tracks([t], tmp_path, env={}, getter=boom)
    assert "no creds" in out["failed"]["t1"] and not list(tmp_path.glob("*.part"))


def test_fetch_picks_s3_when_env_keys_set_else_wrangler(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(A, "_r2_get_s3", lambda k, d, e: (seen.append("s3"), d.write_bytes(b"abc")))
    monkeypatch.setattr(A, "_r2_get_wrangler", lambda k, d, e: (seen.append("wr"), d.write_bytes(b"abc")))
    env = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "b", "R2_SECRET_ACCESS_KEY": "c"}
    A.fetch_missing_tracks([_r2_track(tmp_path)], tmp_path / "x", env=env)
    A.fetch_missing_tracks([_r2_track(tmp_path)], tmp_path / "y", env={})
    assert seen == ["s3", "wr"]


def test_qc_warns_when_pad_used_while_ledger_has_tracks(tmp_path):
    from ullaslab_engine.studio import qc
    w = tmp_path / "work" / "final"
    w.mkdir(parents=True)
    (w / "audio.json").write_text(json.dumps({"short": {"music": {"id": "generated-pad", "fallback": {"fetch_failed": {"t1": "x"}}}}}))
    c = qc.check_music_fallback(tmp_path, "final")
    assert c.status == qc.WARN and "short" in c.detail
    (w / "audio.json").write_text(json.dumps({"short": {"music": {"id": "t1"}}}))
    assert qc.check_music_fallback(tmp_path, "final").status == qc.PASS


@needs_ffmpeg
def test_sfx_are_in_house_audible_short_and_land_on_their_cue(tmp_path):
    import soundfile as sf
    assert "CC0" in A.SFX_PROVENANCE["licence"] and A.SFX_PROVENANCE["cost_usd"] == 0     # generated here, no third-party audio
    lib = A.make_sfx_library(tmp_path / "sfx")
    assert set(lib) == set(A.SFX)
    for name, p in lib.items():
        x, sr = sf.read(str(p))
        assert sr == A.SR and 0.04 <= len(x) / sr <= 3.0 and np.abs(x).max() > 0.05, name
    A.run(A.sfx_stem_cmd([("hit", 2.0), ("tick", 5.0)], lib, 7.0, tmp_path / "s.wav"), "sfx")
    s, sr = sf.read(str(tmp_path / "s.wav"))
    assert abs(len(s) / sr - 7.0) < 0.01
    env = np.abs(s)
    onset = lambda a, b: a + np.flatnonzero(env[int(a * sr):int(b * sr)] > 0.01)[0] / sr
    assert onset(0.0, 3.0) == pytest.approx(2.0, abs=0.02) and onset(3.0, 6.0) == pytest.approx(5.0, abs=0.02)
    assert env[: int(1.9 * sr)].max() < 1e-4                    # nothing before the first cue


# ---------------------------------------------------------------- live-render regression (data_ref left on a kinetic scene)
def _renderer_ref_problems(props: dict) -> list[str]:
    """Mirror of remotion/src/studio/scenes.ts validation: a scene's data_ref must have an entry in refs (footage and kinetic
    scenes excepted when they carry no ref)."""
    bad = []
    for sc in props["scenes"]:
        r = (sc.get("data_ref") or {}).get("ref")
        if r and r not in props["refs"]:
            bad.append(f"{sc['id']}: data_ref {r} not found")
    return bad


def test_flow_scene_without_visual_data_fails_the_render_it_is_never_a_text_card(tmp_path):
    """Live item 2026-11-12: `flow` scenes with no visual_data.json were silently drawn as kinetic text (the video read as slides).
    Watchability slice 1: the assemble stage refuses, naming the scene, and a kinetic scene with a stray ref still drops it."""
    item = make_item(tmp_path, voice=False)
    doc = timed_doc()
    out = doc["outputs"][0]
    s = next(x for x in out["scenes"] if x["type"] == "flow") if any(x["type"] == "flow" for x in out["scenes"]) else out["scenes"][3]
    s["type"], s["data_ref"], s["on_screen_text"] = "flow", {"kind": "data_point", "ref": "DGS10-DGS2"}, "Curve flips"
    with pytest.raises(AssembleError, match=r"flow scene has no entry in visual_data.json.*never turned into a text card"):
        build_props(item, doc, out, tmp_path / "pub", clip_prep=lambda *a: None)
    s["type"] = "timeline"
    with pytest.raises(AssembleError, match="timeline scene has no entry"):
        build_props(item, doc, out, tmp_path / "pub", clip_prep=lambda *a: None)
    # with data it renders as a flow, and a kinetic scene carrying a data_ref still drops it
    s["type"] = "flow"
    (item / "visual_data.json").write_text(json.dumps({"DGS10-DGS2": {
        "meta": {"source": {"name": "FRED", "as_of": "2026-11"}, "freshness": "RECENT"},
        "nodes": [{"id": "a", "label": "A", "level": 0}, {"id": "b", "label": "B", "level": 1}], "edges": [{"from": "a", "to": "b"}]}}))
    k = out["scenes"][0]
    k["type"], k["data_ref"] = "kinetic", {"kind": "data_point", "ref": "DGS3MO"}
    props, warns = build_props(item, doc, out, tmp_path / "pub", clip_prep=lambda *a: None)
    got = {x["id"]: x for x in props["scenes"]}
    assert got[s["id"]]["type"] == "flow" and got[s["id"]]["data_ref"]["ref"] == "DGS10-DGS2"
    assert got[k["id"]]["data_ref"] is None
    assert not any("kinetic text" in w for w in warns)
    assert _renderer_ref_problems(props) == []


@needs_ffmpeg
def test_fixture_through_the_runner_layout_builds_props_the_renderer_accepts(tmp_path):
    """The fixture bundle is zipped and unpacked as the runner does (fetch: safe_unzip; then studio-prepare) and carries the live
    item's shape (a flow scene with data and a windowed chart view); every output's props must pass the renderer's ref check, so fixture-green means live-green."""
    import zipfile
    from ullaslab_engine import io as eio
    from ullaslab_engine.studio import fixture as F
    from ullaslab_engine.studio.actions import jload, prepare_item
    src = tmp_path / "src"
    F.build(src, ref_voice=False)
    z = tmp_path / "bundle.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted((src / "bundle").rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src / "bundle").as_posix())
    work = tmp_path / "runner"
    eio.safe_unzip(z, work / "bundle")
    item = prepare_item(work)
    doc = jload(item / "scenes.json")
    assert any(sc["type"] == "flow" and sc["data_ref"]["kind"] == "data_point" for sc in doc["outputs"][0]["scenes"])
    assert "FIXTURE-POINT" in jload(item / "visual_data.json")
    words = fake_asr_words(" ".join(F.NARRATION))
    for o in doc["outputs"]:
        time_output(o["scenes"], words, 22.0, o["output"])
        props, warns = build_props(item, doc, o, tmp_path / "pub", allow_placeholder=True, clip_prep=lambda *a: None)   # footage comes from the broll stage
        assert _renderer_ref_problems(props) == [], o["output"]
        assert not any("kinetic text" in w for w in warns)
        if o["output"] == "reel":
            assert any(k.startswith("c1@") for k in props["refs"])   # the windowed chart view has its own refs entry


def test_failed_stage_is_logged_as_stage_and_error_class_only(studio_item):
    """The public CI log can only show a safe summary: stage name and exception class, never the message."""
    logs = []

    def boom(*a, **k):
        raise RuntimeError("secret script words")
    s = Studio(studio_item, preview=True, asr=lambda p, l: (fake_asr_words(" ".join(NARRATION)), "fake"), render=boom, log=logs.append)
    with pytest.raises(RuntimeError):
        s.run()
    assert "[failed] render RuntimeError" in logs
    assert not any("secret" in m for m in logs if m.startswith("[failed]"))


def test_error_excerpt_keeps_the_head_and_the_tail():
    from ullaslab_engine.studio.run import _err_excerpt
    t = "HEAD-CAUSE " + "x" * 5000 + " TAIL-STACK"
    e = _err_excerpt(t)
    assert e.startswith("HEAD-CAUSE") and e.endswith("TAIL-STACK") and len(e) < 1200
    assert _err_excerpt("short") == "short"


def test_dub_fixture_builds_bundle_and_master_timing_for_the_dub_job(tmp_path, monkeypatch):
    """The workflow_dispatch dub proof run: public-safe bundle (en + es), synthetic master timing the slot timeline can use."""
    from ullaslab_engine import tts as T
    from ullaslab_engine.audio import Wav
    from ullaslab_engine.bundle import load_bundle
    from ullaslab_engine.studio import fixture as F
    import numpy as np
    monkeypatch.setattr(T, "tts", lambda *a, **k: Wav(np.zeros(2400, dtype=np.float32), 24000))
    F.dub_fixture(tmp_path, "es")
    m = load_bundle(tmp_path / "bundle")
    assert m["languages"] == ["en", "es"] and all("es" in s["text"] for s in m["segments"])
    tl = json.loads((tmp_path / "timing_en.json").read_text())
    assert [s["id"] for s in tl["segments"]] == [s["id"] for s in m["segments"]] and 30 <= tl["total_s"] <= 60
    assert all(a["end"] <= b["start"] for a, b in zip(tl["segments"], tl["segments"][1:]))
    assert (tmp_path / "voice.wav").exists()
