from ullaslab_engine import captions as cap
from ullaslab_engine.bundle import load_bundle


def test_cue_limits_en():
    toks = ("Here is a synthetic example series. Over two years it drifted higher, but the path was far from smooth indeed.").split()
    times = [(i * 0.3, i * 0.3 + 0.3) for i in range(len(toks))]
    cues = cap.segment_cues(toks, times, "en")
    for c in cues:
        assert len(c["lines"]) <= 2 and all(len(l) <= 32 for l in c["lines"])
    assert " ".join(l for c in cues for l in c["lines"]).split() == toks


def test_japanese_uses_half_width_budget_and_no_spaces():
    text = "これは合成された例です。二年間でゆっくりと上昇しましたが、道のりは平坦ではありませんでした。"
    toks = cap.tokenise(text, "ja")
    cues = cap.segment_cues(toks, [(i * 0.2, i * 0.2 + 0.2) for i in range(len(toks))], "ja")
    assert all(len(l) <= 16 for c in cues for l in c["lines"]) and len(cues) > 1


def test_align_words_uses_asr_and_interpolates_misses():
    script = "the quick brown fox jumps".split()
    asr = [("The", 0.0, 0.2), ("quick", 0.2, 0.5), ("fox,", 1.0, 1.3), ("jumps.", 1.3, 1.7)]
    al = cap.align_words(script, asr)
    assert al[1] == (0.2, 0.5) and al[2] is None and al[3] == (1.0, 1.3)
    filled = cap._fill(al, script, 0.0, 2.0)
    assert filled[2][0] >= 0.5 and filled[2][1] <= 1.0


def test_srt_vtt_format():
    cues = [{"start": 0.0, "end": 1.5, "lines": ["a", "b"]}, {"start": 1.5, "end": 3.0, "lines": ["c"]}]
    srt, vtt = cap.to_srt(cues), cap.to_vtt(cues)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\na\nb\n\n2\n")
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.500")


def test_translated_captions_follow_master_segment_windows(bundle_dir):
    m = load_bundle(bundle_dir)
    for s in m["segments"]:
        s["text"]["hi"] = "यह एक कृत्रिम उदाहरण है जो केवल परीक्षण के लिए बनाया गया है और इसका कोई अर्थ नहीं है"
    windows = {s["id"]: (10.0 * i, 10.0 * i + 6.0) for i, s in enumerate(m["segments"])}
    cues = cap.build_cues(m, "hi", windows)
    assert cues[0]["start"] >= 0 and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(cues, cues[1:]))
    seg_ends = {v[1] for v in windows.values()}
    assert all(c["end"] <= max(seg_ends) + 1.01 for c in cues)
    assert all(len(l) <= 32 for c in cues for l in c["lines"])
    # each segment's cues lie inside its window (plus the 0.6 s minimum-duration allowance)
    for i, (a, b) in enumerate(windows.values()):
        inside = [c for c in cues if a - 1e-6 <= c["start"] < b]
        assert inside


def test_arabic_is_space_delimited_and_untouched():
    assert cap.tokenise("مرحبا بكم في القناة", "ar") == ["مرحبا", "بكم", "في", "القناة"]
