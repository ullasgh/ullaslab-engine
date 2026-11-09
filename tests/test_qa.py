import copy
import json
import numpy as np
from conftest import fake_tts_factory, speechlike
from ullaslab_engine import qa as Q
from ullaslab_engine.audio import Wav, normalize_loudness
from ullaslab_engine.bundle import load_bundle
from ullaslab_engine.synth import natural_timeline, synth_segments


def setup(bundle_dir):
    m = load_bundle(bundle_dir)
    audio, tl = natural_timeline(m, "en", synth_segments(m, "en", None, fake_tts_factory(2.7)))
    return m, normalize_loudness(audio), tl


def good_layout(W=1080, H=1920, frames=1):
    el = [{"role": "bg", "x": 0, "y": 0, "w": W, "h": H, "fontPx": 16, "fg": "#f2f5f9", "bg": "#0e1726", "words": 0},
          {"role": "headline", "x": 60, "y": 300, "w": 900, "h": 90, "fontPx": 72, "fg": "#f2f5f9", "bg": "#0e1726", "words": 3},
          {"role": "axis", "x": 80, "y": 500, "w": 80, "h": 40, "fontPx": 36, "fg": "#a9b6c8", "bg": "#16233a", "words": 1},
          {"role": "caption", "x": 100, "y": 1300, "w": 800, "h": 120, "fontPx": 44, "fg": "#f2f5f9", "bg": "#0a1220", "words": 12}]
    return {"width": W, "height": H, "frames": [{"frame": i, "scene": "s", "elements": copy.deepcopy(el)} for i in range(frames)]}


def run(m, wav, tl, layout, err=0.5, cues=None, orient="vertical"):
    cues = cues if cues is not None else [{"start": 0, "end": 2, "lines": ["short line", "another short"]}]
    return Q.run_qa(m, "en", wav, tl, cues, layout, err, orient)


def failed(qa):
    return {(g, c["name"]) for g, v in qa["gates"].items() for c in v["checks"] if not c["passed"]}


def test_clean_pass(bundle_dir):
    m, w, tl = setup(bundle_dir)
    qa = run(m, w, tl, good_layout())
    assert qa["passed"], failed(qa)


def test_loudness_and_peak_breach(bundle_dir):
    m, w, tl = setup(bundle_dir)
    quiet = Wav(w.samples * 0.2, w.sr)
    assert ("A3", "lufs") in failed(run(m, quiet, tl, good_layout()))
    hot = Wav(np.clip(w.samples * 4, -1, 1), w.sr)
    assert ("A3", "true_peak_dbtp") in failed(run(m, hot, tl, good_layout()))


def test_wer_gate(bundle_dir):
    m, w, tl = setup(bundle_dir)
    assert ("A3", "wer_pct") in failed(run(m, w, tl, good_layout(), err=3.5))
    assert ("A3", "wer_pct") in failed(run(m, w, tl, good_layout(), err=None))
    assert ("A3", "wer_pct") not in failed(run(m, w, tl, good_layout(), err=3.0))


def test_safe_zone_breaches(bundle_dir):
    m, w, tl = setup(bundle_dir)
    for key, val in [("y", 100), ("x", 20), ("y", 1700)]:
        lay = good_layout()
        lay["frames"][0]["elements"][1][key] = val
        assert ("A5", "elements_outside_safe_zone") in failed(run(m, w, tl, lay)), (key, val)
    lay = good_layout(); lay["frames"][0]["elements"][1]["w"] = 1000  # right edge 1060 > 1020
    assert ("A5", "elements_outside_safe_zone") in failed(run(m, w, tl, lay))


def test_text_size_contrast_words_and_frame_size(bundle_dir):
    m, w, tl = setup(bundle_dir)
    lay = good_layout(); lay["frames"][0]["elements"][1]["fontPx"] = 40
    assert ("A5", "body_text_below_min_px") in failed(run(m, w, tl, lay))
    lay = good_layout(); lay["frames"][0]["elements"][2]["fontPx"] = 30
    assert ("A5", "label_text_below_min_px") in failed(run(m, w, tl, lay))
    lay = good_layout(); lay["frames"][0]["elements"][1]["fg"] = "#555555"
    assert ("A5", "contrast_failures") in failed(run(m, w, tl, lay))
    lay = good_layout(); lay["frames"][0]["elements"][1]["words"] = 13
    assert ("A5", "max_non_caption_words_per_scene") in failed(run(m, w, tl, lay))
    lay = good_layout(); lay["frames"][0]["elements"].append({"role": "legal", "x": 60, "y": 900, "w": 900, "h": 300, "fontPx": 48, "fg": "#f2f5f9", "bg": "#0e1726", "words": 30})
    assert ("A5", "max_non_caption_words_per_scene") not in failed(run(m, w, tl, lay))  # legal text is exempt
    assert ("A5", "frame_size") in failed(run(m, w, tl, good_layout(W=1920, H=1080)))
    assert ("A5", "layout_audit") in failed(run(m, w, tl, None))


def test_caption_limits(bundle_dir):
    m, w, tl = setup(bundle_dir)
    assert ("A5", "caption_lines") in failed(run(m, w, tl, good_layout(), cues=[{"start": 0, "end": 1, "lines": ["a", "b", "c"]}]))
    assert ("A5", "caption_chars_per_line") in failed(run(m, w, tl, good_layout(), cues=[{"start": 0, "end": 1, "lines": ["x" * 33]}]))


def test_duration_and_pacing(bundle_dir):
    m, w, tl = setup(bundle_dir)
    long_tl = copy.deepcopy(tl); long_tl["total_s"] = 75
    assert ("duration", "duration_s") in failed(run(m, w, long_tl, good_layout()))
    over = copy.deepcopy(tl); over["overruns"] = ["a1"]
    assert ("duration", "dub_overruns") in failed(run(m, w, over, good_layout()))
    slow = copy.deepcopy(tl); slow["scenes"][1]["beats"] = [slow["scenes"][1]["start"]]; slow["scenes"][1]["end"] = slow["scenes"][1]["start"] + 9
    assert ("A4", "max_seconds_between_changes") in failed(run(m, w, slow, good_layout()))
    short = copy.deepcopy(tl); short["scenes"][1]["end"] = short["scenes"][1]["start"] + 1
    assert ("A4", "scene_len_min_s") in failed(run(m, w, short, good_layout()))


def test_a1_claim_id_and_hash(bundle_dir):
    m, w, tl = setup(bundle_dir)
    m2 = copy.deepcopy(m)
    del m2["scenes"][0]["chart_data"]["claim_id"]
    assert ("A1", "charts_with_claim_id") in failed(run(m2, w, tl, good_layout()))
    m3 = copy.deepcopy(m)
    m3["scenes"][0]["chart_data"]["series"][0]["points"][0]["y"] += 1
    assert ("A1", "chart_hash_matches") in failed(run(m3, w, tl, good_layout()))
    assert Q.chart_hash(m["scenes"][0]["chart_data"]) == m["scenes"][0]["chart_data"]["chart_hash"]


def test_qa_json_contains_numbers_only(bundle_dir):
    m, w, tl = setup(bundle_dir)
    s = json.dumps(run(m, w, tl, good_layout()))
    for seg in m["segments"]:
        assert seg["text"]["en"][:20] not in s
    assert "http" not in s and "synthetic" not in s.lower()


def test_wpm_gate_catches_fast_speech(bundle_dir):
    m = load_bundle(bundle_dir)
    audio, tl = natural_timeline(m, "en", synth_segments(m, "en", None, fake_tts_factory(4.5)))
    assert ("A3", "wpm") in failed(run(m, normalize_loudness(audio), tl, good_layout()))


def test_contrast_ratio_math():
    assert abs(Q.contrast_ratio("#000000", "#ffffff") - 21) < 0.01


def test_qa_lines_are_numbers_only(bundle_dir):
    from ullaslab_engine.cli import qa_lines
    m, wav, tl = setup(bundle_dir)
    qa = run(m, wav, tl, good_layout(), err=9.0)
    lines = qa_lines(qa)
    assert "A3.wer_pct=9.0 limit=3 FAIL" in lines
    assert any(l.startswith("duration.duration_s=") for l in lines)
    blob = " ".join(lines)
    for s in m["segments"]:
        assert s["text"]["en"][:20] not in blob
