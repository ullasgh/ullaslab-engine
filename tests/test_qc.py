"""WP5 QC tests. Tiny lavfi fixture videos (192x108, 30 fps, 8 s) each carrying one fault; every detector must catch its fault
and stay quiet on the clean one. No network."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import pytest
import soundfile as sf

from ullaslab_engine.studio import qc as Q

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
SIZE = (192, 108)
T = Q.thresholds()
SRC = {
    "A": "testsrc2=s=192x108:r=30:d=3",
    "B": "gradients=s=192x108:r=30:d=3:speed=0.5:seed=3:c0=red:c1=blue:nb_colors=2",
    "C": "gradients=s=192x108:r=30:d=3:speed=0.4:seed=9:c0=yellow:c1=green:nb_colors=2",
    "black": "color=c=black:s=192x108:r=30:d=1",
    "still": "color=c=0x336699:s=192x108:r=30:d=3",
}


def speechlike(seconds: float, lufs: float = -14.0, gaps=(), clip: bool = False) -> np.ndarray:
    """Amplitude-modulated tones (never silent) normalised to `lufs`; `gaps` zero out (start, end) windows."""
    sr = 48000
    t = np.arange(int(seconds * sr)) / sr
    x = np.sin(2 * np.pi * 220 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 3 * t)) + 0.3 * np.sin(2 * np.pi * 1300 * t) * np.sin(2 * np.pi * 1.7 * t)
    x = x / np.abs(x).max() * 0.5
    x = x * 10 ** ((lufs - pyln.Meter(sr).integrated_loudness(x)) / 20)
    for a, b in gaps:
        x[int(a * sr):int(b * sr)] = 0
    return np.clip(x * (4.0 if clip else 1.0), -1, 1).astype(np.float32) if clip else x.astype(np.float32)


def build(dst: Path, parts: list[str], audio: np.ndarray | None = None, faststart: bool = True) -> Path:
    wav = dst.with_suffix(".wav")
    sf.write(str(wav), audio if audio is not None else speechlike(sum(float(SRC[p].split("d=")[1].split(":")[0]) if "d=" in SRC[p] else 3 for p in parts)), 48000)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in parts:
        cmd += ["-f", "lavfi", "-i", SRC[p]]
    cmd += ["-i", str(wav), "-filter_complex", "".join(f"[{i}:v]format=yuv420p,setsar=1[v{i}];" for i in range(len(parts))) +
            "".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]", "-map", "[v]", "-map", f"{len(parts)}:a",
            "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-ar", "48000", "-shortest"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    subprocess.run(cmd + [str(dst)], check=True)
    return dst


def dur(p: Path) -> float:
    return float(Q.probe(p)["format"]["duration"])


@pytest.fixture(scope="module")
def vids(tmp_path_factory):
    d = tmp_path_factory.mktemp("qcvids")
    v = {"clean": build(d / "clean.mp4", ["A", "B", "C"]),
         "black": build(d / "black.mp4", ["A", "black", "B", "black", "C"]),     # 1 s of black mid-video (twice) -> not an edge fade
         "frozen": build(d / "frozen.mp4", ["A", "still", "C"]),
         "loud": build(d / "loud.mp4", ["A", "B", "C"], audio=speechlike(9, lufs=-6, clip=True)),
         "dup": build(d / "dup.mp4", ["A", "B", "A"]),
         "slow": build(d / "slow.mp4", ["A", "B", "C"], faststart=False)}
    v["silent"] = build(d / "silent.mp4", ["A", "B", "C"], audio=speechlike(9, gaps=[(3.0, 5.5)]))
    return v


def status(checks, name_part):
    return [c.status for c in checks if name_part in c.name]


# ---------------------------------------------------------------- spec
def test_spec_clean_passes_and_wrong_size_fails(vids):
    ok = Q.check_spec(vids["clean"], SIZE, vids["clean"].with_suffix(".wav"), T)
    assert {c.status for c in ok} == {Q.PASS}, [c for c in ok if c.status != Q.PASS]
    bad = Q.check_spec(vids["clean"], (1920, 1080), None, T)
    assert "FAIL" in status(bad, "video format")


def test_faststart_detected(vids):
    assert Q.faststart(vids["clean"]) and not Q.faststart(vids["slow"])
    assert Q.FAIL in status(Q.check_spec(vids["slow"], SIZE, None, T), "faststart")


def test_duration_vs_voice_tolerance(vids, tmp_path):
    short = tmp_path / "v.wav"
    sf.write(str(short), speechlike(6.0), 48000)
    assert Q.FAIL in status(Q.check_spec(vids["clean"], SIZE, short, T), "duration vs voice")


# ---------------------------------------------------------------- black / frozen / silent
def test_black_gap_caught_and_clean_is_clean(vids):
    assert Q.check_black(vids["clean"], dur(vids["clean"]), None, T).status == Q.PASS
    c = Q.check_black(vids["black"], dur(vids["black"]), None, T)
    assert c.status == Q.FAIL and "black" in c.detail


def test_black_dip_to_black_transition_is_allowed(vids):
    d = dur(vids["black"])
    scenes = [{"id": "s1", "type": "kinetic", "transition": "dip_to_black", "narration": {"start_s": 0, "end_s": 3.0}},
              {"id": "s2", "type": "kinetic", "transition": "dip_to_black", "narration": {"start_s": 3.0, "end_s": 7.0}},
              {"id": "s3", "type": "kinetic", "transition": "cut", "narration": {"start_s": 7.0, "end_s": d}}]
    assert Q.check_black(vids["black"], d, scenes, T).status == Q.PASS


def test_freeze_caught_unless_deliberate_hold(vids):
    d = dur(vids["frozen"])
    assert Q.check_freeze(vids["clean"], dur(vids["clean"]), None, T).status == Q.PASS
    assert Q.check_freeze(vids["frozen"], d, None, T).status == Q.FAIL
    hold = [{"id": "s2", "type": "kinetic", "hold": True, "narration": {"start_s": 3.0, "end_s": 6.0}}]
    assert Q.check_freeze(vids["frozen"], d, hold, T).status == Q.PASS


def test_silence_over_limit_caught(vids):
    assert Q.check_silence(vids["clean"], dur(vids["clean"]), "mix silence", T).status == Q.PASS
    c = Q.check_silence(vids["silent"], dur(vids["silent"]), "mix silence", T)
    assert c.status == Q.FAIL and "silence" in c.detail


# ---------------------------------------------------------------- loudness
def test_loudness_clean_in_range_and_loud_fails(vids):
    ok = Q.check_loudness(vids["clean"], T)
    assert [c.status for c in ok] == [Q.PASS] * 3, ok
    loud = Q.check_loudness(vids["loud"], T)
    assert [c.status for c in loud] == [Q.FAIL, Q.FAIL, Q.FAIL], loud   # LUFS, true peak and clipping all caught


# ---------------------------------------------------------------- repeated clips
def test_perceptual_hash_catches_repeated_shot(vids):
    assert Q.check_phash(vids["clean"], dur(vids["clean"]), None, T).status == Q.PASS
    c = Q.check_phash(vids["dup"], dur(vids["dup"]), None, T)
    assert c.status == Q.FAIL and "distance" in c.detail


def test_asset_sha_duplicate_in_one_output(tmp_path):
    def ledger(h2):
        (tmp_path / "assets.json").write_text(json.dumps({"assets": [
            {"filename": "footage/long/s02.mp4", "scene": "s02", "output": "long", "sha256": "a" * 64},
            {"filename": "footage/long/s03.mp4", "scene": "s03", "output": "long", "sha256": h2},
            {"filename": "footage/short/s02.mp4", "scene": "s02", "output": "short", "sha256": "a" * 64}]}))
    ledger("a" * 64)
    assert Q.check_asset_duplicates(tmp_path, "long").status == Q.FAIL
    assert Q.check_asset_duplicates(tmp_path, "short").status == Q.PASS      # the same clip in a different output is fine
    ledger("b" * 64)
    assert Q.check_asset_duplicates(tmp_path, "long").status == Q.PASS


# ---------------------------------------------------------------- captions
def _words(n=12, t0=0.3):
    out, t = [], t0
    for i in range(n):
        out.append({"w": f"w{i}", "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.4
    return out


def test_srt_sync_flags_drift_over_150ms(tmp_path):
    words = _words()
    scenes = [{"narration": {"words": words}}]
    from ullaslab_engine.studio.captions import cues_to_srt
    cues = [{"start": words[i]["start"], "end": words[i + 3]["end"] + 0.35, "lines": [words[i:i + 4]]} for i in range(0, 12, 4)]
    p = tmp_path / "a.srt"
    p.write_text(cues_to_srt(cues))
    assert Q.check_caption_sync(p, scenes, T).status == Q.PASS
    cues[1]["start"] += 0.2
    p.write_text(cues_to_srt(cues))
    c = Q.check_caption_sync(p, scenes, T)
    assert c.status == Q.FAIL and "cue 2" in c.detail
    assert Q.check_caption_sync(None, scenes, T).status == Q.FAIL


def _frame(text_box=None, size=(540, 960)):
    img = np.full((size[1], size[0], 3), (14, 24, 44), dtype=np.uint8)       # dark brand plate
    if text_box:
        x0, y0, x1, y1 = text_box
        img[y0:y1, x0:x1] = (245, 245, 245)                                  # stand-in for white caption / key text
    return img


def test_margin_text_detector():
    box = (30, 110, 475, 750)                                                # vertical safe box at half scale
    w_in, m = Q.margin_text_pixels(_frame((60, 300, 400, 340)), box)
    assert w_in == 0 and m > 0
    w_out, m = Q.margin_text_pixels(_frame((60, 800, 400, 840)), box)        # inside the bottom UI zone
    assert w_out == 340 * 40 and w_out / m > Q.thresholds()["margin_white_frac"]


def test_caption_frames_fail_when_text_leaves_safe_box(tmp_path):
    from PIL import Image

    def video(box):
        png = tmp_path / "f.png"
        Image.fromarray(_frame(box)).save(png)
        v = tmp_path / "c.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(png), "-t", "2", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "12", str(v)], check=True)
        return v
    props = {"width": 1080, "captions": [{"start": 0.2, "end": 1.8, "lines": [[{"w": "x", "start": 0.2, "end": 0.5}]]}]}
    assert Q.check_caption_frames(video((60, 300, 400, 340)), props, None, (540, 960), "vertical", T).status == Q.PASS
    c = Q.check_caption_frames(video((60, 800, 400, 840)), props, None, (540, 960), "vertical", T)
    assert c.status == Q.FAIL and "outside safe box" in c.detail


def test_caption_layout_limits():
    cue = {"start": 0, "end": 1, "lines": [[{"w": "a" * 40, "start": 0, "end": 1}]]}
    assert Q.check_caption_layout({"captions": [cue]}, "vertical", T).status == Q.FAIL
    cue["lines"] = [[{"w": "ok", "start": 0, "end": 1}]]
    assert Q.check_caption_layout({"captions": [cue]}, "vertical", T).status == Q.PASS


# ---------------------------------------------------------------- data integrity + platform
PACK = "# Pack\n\n## Description (long)\n\nEducation only. Not investment advice. Not SEBI/SEC registered. Data may be delayed. Do your own research.\n\nBody.\n\n## AI disclosure recommendation\n"


def _item(tmp_path, chart_extra=None, meta=None, publish=PACK):
    from studio_fixture import chart, scenes_doc
    item = tmp_path / "2026-11-10-x"
    item.mkdir()
    c = chart()
    c["c1"].update(chart_extra or {})
    (item / "chart_specs.json").write_text(json.dumps(c))
    (item / "meta.json").write_text(json.dumps(meta if meta is not None else {"synthetic_voice": True, "ai_label": True}))
    (item / "publish.md").write_text(publish)
    doc = scenes_doc(item.name)
    for o in doc["outputs"]:      # drop footage scenes (ledger checks have their own test)
        for sc in o["scenes"]:
            if sc["type"] == "footage":
                sc["type"], sc["on_screen_text"] = "kinetic", "Plain words"
    return item, doc


def test_chart_hash_must_match_ledger(tmp_path):
    from ullaslab_engine.qa import chart_hash
    from studio_fixture import chart
    item, doc = _item(tmp_path)
    good = chart_hash(chart()["c1"])
    (item / "sources.md").write_text(f"| claim | figure | tag | chart_hash |\n|---|---|---|---|\n| c1 | 10y yield | INFERRED | {good} |\n")
    assert [c.status for c in Q.check_data(item, doc, False) if "hash" in c.name] == [Q.PASS]
    (item / "sources.md").write_text("| claim | figure | tag | chart_hash |\n|---|---|---|---|\n| c1 | 10y yield | INFERRED | " + "0" * 64 + " |\n")
    assert [c.status for c in Q.check_data(item, doc, False) if "hash" in c.name] == [Q.FAIL]
    (item / "sources.md").unlink()
    assert [c.status for c in Q.check_data(item, doc, False) if "hash" in c.name] == [Q.WARN]    # no recorded hash: visible, not blocking


def test_unresolved_data_ref_and_untagged_chart_fail(tmp_path):
    item, doc = _item(tmp_path)
    doc["outputs"][0]["scenes"][2]["data_ref"]["ref"] = "nope"
    c = Q.check_data(item, doc, False)
    assert c[0].status == Q.FAIL and "nope" in c[0].detail
    item2, doc2 = _item(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, chart_extra={"freshness": "STALE"})
    assert [x.status for x in Q.check_data(item2, doc2, False) if x.name.endswith("tag")] == [Q.FAIL]


def test_untagged_number_on_screen_fails_until_ledger_row_tags_it(tmp_path):
    item, doc = _item(tmp_path)
    doc["outputs"][0]["scenes"][0]["on_screen_text"] = "Yield hit 4.5%"
    assert [x.status for x in Q.check_data(item, doc, False) if x.name.endswith("tag")] == [Q.FAIL]
    (item / "sources.md").write_text("| claim | figure | tag |\n|---|---|---|\n| yield | 4.5% | RECENT |\n")
    assert [x.status for x in Q.check_data(item, doc, False) if x.name.endswith("tag")] == [Q.PASS]


def test_footage_ledger_completeness(tmp_path):
    from studio_fixture import make_item
    item = make_item(tmp_path)
    doc = json.loads((item / "scenes.json").read_text())
    names = [c for c in Q.check_data(item, doc, False) if c.name == "footage ledger complete"]
    assert names[0].status == Q.PASS
    led = json.loads((item / "assets.json").read_text())
    del led["assets"][0]["illustrative"]
    led["assets"][1]["licence"]["name"] = ""
    led["assets"].pop(2)
    (item / "assets.json").write_text(json.dumps(led))
    c = [c for c in Q.check_data(item, doc, False) if c.name == "footage ledger complete"][0]
    assert c.status == Q.FAIL and "illustrative" in c.detail and "licence.name" in c.detail and "no ledger entry" in c.detail
    assert [c for c in Q.check_data(item, doc, True) if c.name == "footage ledger complete"][0].status == Q.WARN    # preview: placeholders allowed


@pytest.mark.parametrize("text,hit", [("Source: Schwab", "Schwab"), ("via yfinance", "yfinance"), ("data from investing.com", "investing.com"),
                                      ("FYERS quotes", "FYERS"), ("NSE feed", "NSE feed"), ("Atlas MCP says", "Atlas"), ("Natural Earth, world-atlas", None),
                                      ("An atlas of ideas", None), ("Treasury yields", None)])
def test_deny_listed_names(tmp_path, text, hit):
    item, doc = _item(tmp_path)
    doc["outputs"][0]["scenes"][0]["on_screen_text"] = text
    c = Q.check_deny(item, "final", doc, {})
    assert (c.status == Q.FAIL) == bool(hit) and (not hit or hit in c.detail)


def test_platform_readiness(tmp_path):
    item, _ = _item(tmp_path)
    assert {c.status for c in Q.check_platform(item)} == {Q.PASS}
    (item / "meta.json").write_text(json.dumps({"synthetic_voice": False}))
    (item / "publish.md").write_text("# Pack\n")
    assert [c.status for c in Q.check_platform(item)] == [Q.FAIL] * 3


def test_disclaimer_must_be_first_description_line(tmp_path):
    item, _ = _item(tmp_path)
    c = [x for x in Q.check_platform(item) if x.name.startswith("disclaimer")][0]
    assert c.status == Q.PASS
    (item / "publish.md").write_text(PACK.replace("Education only. Not investment", "Hello there.\n\nEducation only. Not investment"))
    c = [x for x in Q.check_platform(item) if x.name.startswith("disclaimer")][0]
    assert c.status == Q.FAIL                       # present but not the first line


def test_end_line_check(tmp_path):
    item, doc = _item(tmp_path)
    assert Q.check_end_line(item, "final", doc).status == Q.PASS
    doc["outputs"][1]["scenes"][-1]["narration"]["text"] = "Education only. Not investment advice. Not SEBI/SEC registered."
    c = Q.check_end_line(item, "final", doc)
    assert c.status == Q.FAIL and "short" in c.detail
    doc["outputs"][1]["scenes"][-1]["narration"]["text"] = "Done. Follow UllasLab. Education only."
    wm = item / "work" / "final"
    wm.mkdir(parents=True)
    (wm / "props.long.json").write_text(json.dumps({"durationInFrames": 600}))
    assert Q.check_end_line(item, "final", doc).status == Q.FAIL            # props carry no endCard
    (wm / "props.long.json").write_text(json.dumps({"durationInFrames": 600, "endCard": {"fromFrame": 510, "durationInFrames": 90}}))
    assert Q.check_end_line(item, "final", doc).status == Q.PASS


@pytest.mark.parametrize("where,text", [("on_screen", "Yield 4.5% LAGGED"), ("on_screen", "RECENT"), ("props", "INFERRED"), ("caption", "LIVE data"),
                                        ("srt", "EXPECTATION"), ("narration", "Not SEBI/SEC registered"), ("narration", "Data may be delayed")])
def test_freshness_tag_words_and_old_readouts_fail_on_screen(tmp_path, where, text):
    item, doc = _item(tmp_path)
    sc = doc["outputs"][0]["scenes"][0]
    wm = item / "work" / "final"
    wm.mkdir(parents=True)
    srts = {}
    if where == "on_screen":
        sc["on_screen_text"] = text
    elif where == "narration":
        sc["narration"]["text"] = text
    elif where == "props":
        (wm / "props.long.json").write_text(json.dumps({"scenes": [], "refs": {"c1": {"meta": {"badge": text}}}, "captions": []}))
    elif where == "caption":
        (wm / "props.long.json").write_text(json.dumps({"scenes": [], "refs": {}, "captions": [{"lines": [[{"w": text}]]}]}))
    elif where == "srt":
        (item / "c.srt").write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n")
        srts = {"long": item / "c.srt"}
    assert Q.check_onscreen_labels(item, "final", doc, srts).status == Q.FAIL


def test_freshness_tags_in_ledger_fields_do_not_fail_on_screen_check(tmp_path):
    item, doc = _item(tmp_path)
    wm = item / "work" / "final"
    wm.mkdir(parents=True)
    (wm / "props.long.json").write_text(json.dumps({"scenes": [{"id": "s1", "type": "chart", "on_screen_text": "Ten year yield"}],
                                                    "refs": {"c1": {"meta": {"freshness": "LAGGED", "source": {"name": "FRED", "as_of": "2026-11"}}}}, "captions": []}))
    assert Q.check_onscreen_labels(item, "final", doc, {}).status == Q.PASS
    (item / "sources.md").write_text("| claim | figure | tag |\n|---|---|---|\n| yield | 4.5% | LAGGED |\n")   # ledgers keep tags
    assert Q.check_data(item, doc, False)


def test_platform_preview_without_pack_warns_not_fails(tmp_path):
    item, _ = _item(tmp_path)
    (item / "publish.md").unlink()
    assert sorted(c.status for c in Q.check_platform(item, preview=True)) == [Q.PASS, Q.WARN, Q.WARN]
    assert Q.FAIL in [c.status for c in Q.check_platform(item, preview=False)]


# ---------------------------------------------------------------- orchestration
def test_qc_output_runs_all_detectors_and_writes_contact_sheet(vids, tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    ok, sheet = Q.qc_output(vids["clean"], size=SIZE, orient="vertical", voice=vids["clean"].with_suffix(".wav"), scenes=None, props=None, srt=None,
                            item=item, name="long", sheet_to=tmp_path / "sheet.png")
    assert sheet and sheet.is_file()
    from PIL import Image
    assert Image.open(sheet).size[0] == 4 * 384
    by = {c.name: c.status for c in ok}
    assert by["faststart"] == by["integrated loudness"] == by["black frames"] == by["frozen frames"] == Q.PASS
    assert "abrupt ending" in by and "narration ends cleanly" in by       # M2b ending checks are wired into qc_output
    bad, _ = Q.qc_output(vids["black"], size=SIZE, orient="vertical", voice=None, scenes=None, props=None, srt=None, item=item, name="long")
    assert Q.FAIL in [c.status for c in bad if c.name == "black frames"]


def test_report_verdict_and_markdown():
    r = Q.Report("x", "final", {"long": [Q.Check("spec", "a", Q.PASS, "ok"), Q.Check("audio", "b", Q.WARN, "hmm")]},
                 [Q.Check("data", "c", Q.FAIL, "bad | pipe")])
    assert r.verdict("long") == Q.WARN and r.verdict() == Q.FAIL
    md = r.markdown()
    assert "Overall: FAIL" in md and "bad / pipe" in md and "FAIL [item] data/c" in md
    assert r.as_dict()["outputs"]["long"]["verdict"] == Q.WARN


def test_clipping_is_per_channel_not_a_mono_sum(tmp_path):
    """Regression: a stereo file with identical quiet channels must not look clipped (a -ac 1 downmix sums them)."""
    x = speechlike(4, lufs=-17.0)
    st = build(tmp_path / "st.mp4", ["A"], audio=np.stack([x[:48000 * 3], x[:48000 * 3]], axis=1))
    assert Q.probe(st)["streams"][1]["channels"] == 2
    runs, peak = Q.clipping(st, T)
    assert runs == 0 and peak < 0.9


def test_loop_inside_one_scene_is_not_a_duplicate(vids):
    d = dur(vids["dup"])
    one = [{"id": "s1", "type": "footage", "narration": {"start_s": 0.0, "end_s": d}}]
    assert Q.check_phash(vids["dup"], d, one, T).status == Q.PASS
    two = [{"id": "s1", "type": "footage", "narration": {"start_s": 0.0, "end_s": 3.0}},
           {"id": "s2", "type": "footage", "narration": {"start_s": 3.0, "end_s": 6.0}},
           {"id": "s3", "type": "footage", "narration": {"start_s": 6.0, "end_s": d}}]
    c = Q.check_phash(vids["dup"], d, two, T)
    assert c.status == Q.FAIL and "s1/s3" in c.detail
    two[0]["type"] = "kinetic"
    assert Q.check_phash(vids["dup"], d, two, T).status == Q.WARN     # a repeated non-footage backdrop is only a warning


@pytest.mark.parametrize("where", ["narration", "on_screen", "srt", "publish_hashtag", "publish_title", "meta", "thumb", "props"])
def test_banned_word_macro_fails_everywhere_audience_sees_it(tmp_path, where):
    item, doc = _item(tmp_path)
    sc = doc["outputs"][0]["scenes"][0]
    wm = item / "work" / "final"
    wm.mkdir(parents=True)
    srts = {}
    if where == "narration":
        sc["narration"]["text"] = "Today we cover Macroeconomics basics"
    elif where == "on_screen":
        sc["on_screen_text"] = "The macro view"
    elif where == "srt":
        (item / "c.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nmacro moves\n\n")
        srts = {"long": item / "c.srt"}
    elif where == "publish_hashtag":
        (item / "publish.md").write_text("# Pack\n\n## Hashtags\n\n#markets #macro\n")
    elif where == "publish_title":
        (item / "publish.md").write_text("# Pack\n\n1. A macroeconomic puzzle\n")
    elif where == "meta":
        (item / "meta.json").write_text(json.dumps({"description": "macro"}))
    elif where == "thumb":
        (wm / "props.thumb.json").write_text(json.dumps({"headline": "Macro shock"}))
    elif where == "props":
        (wm / "props.long.json").write_text(json.dumps({"scenes": [], "refs": {"c1": {"meta": {"source": {"name": "Macro Data Inc"}}}}, "captions": []}))
    c = Q.check_banned_word(item, "final", doc, srts, Q.thresholds())
    assert c.status == Q.FAIL, c


def test_banned_word_no_brand_exception_by_default_but_configurable(tmp_path):
    item, doc = _item(tmp_path)
    (item / "publish.md").write_text("# Pack\n\nBy UllasLab Macro. Education only.\n")
    T2 = Q.thresholds()
    assert T2["brand_allow"] == []
    assert Q.check_banned_word(item, "final", doc, {}, T2).status == Q.FAIL        # no brand exception: "UllasLab Macro" fails
    assert Q.check_banned_word(item, "final", doc, {}, {**T2, "brand_allow": ["UllasLab Macro"]}).status == Q.PASS   # the one config value
    (item / "publish.md").write_text("# Pack\n\nBy UllasLab. Education only.\n")
    assert Q.check_banned_word(item, "final", doc, {}, T2).status == Q.PASS
    doc["outputs"][0]["scenes"][0]["on_screen_text"] = "#macro and Macroeconomics"
    assert Q.check_banned_word(item, "final", doc, {}, T2).status == Q.FAIL


def test_platform_safe_boxes():
    import json
    from ullaslab_engine.config import ROOT
    from ullaslab_engine.studio.layout_check import platform_box, caption_boxes, check
    z = json.loads((ROOT / "config" / "safe_zones.json").read_text())["platforms"]
    both = Q.safe_box("vertical")
    yt, ig = Q.safe_box("vertical", "youtube_shorts"), Q.safe_box("vertical", "instagram_reels")
    assert yt == {k: z["youtube_shorts"][k] for k in ("top", "bottom", "left", "right")}
    assert ig["right"] == 130 and yt["right"] == 192 and ig["top"] == 269 and yt["top"] == 288
    for k in ("top", "bottom", "left", "right"):                       # one render serving both uses the stricter of the two
        assert both[k] == max(yt[k], ig[k])
    assert Q.safe_box("horizontal", "youtube_shorts") == Q.safe_box("horizontal")   # platform only changes vertical
    assert platform_box("vertical", "youtube_shorts", "ad")["bottom"] == 672
    assert platform_box("vertical", "both", "ad")["bottom"] == 672
    assert caption_boxes("vertical", platform="instagram_reels")["safe"][2] > caption_boxes("vertical")["safe"][2]
    assert check("vertical", platform="youtube_shorts") == []
    with pytest.raises(ValueError):
        platform_box("vertical", "tiktok")


def test_caption_frames_per_platform_override(tmp_path):
    from PIL import Image
    # half-scale frame: text in x 450..470 sits in the Reels-only right-rail band (both box ends at x=444, Reels box at x=475)
    png = tmp_path / "f.png"
    Image.fromarray(_frame((450, 300, 470, 380))).save(png)
    v = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(png), "-t", "2", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "12", str(v)], check=True)
    props = {"width": 1080, "captions": [{"start": 0.2, "end": 1.8, "lines": [[{"w": "x", "start": 0.2, "end": 0.5}]]}]}
    assert Q.check_caption_frames(v, props, None, (540, 960), "vertical", T, "instagram_reels").status == Q.PASS
    assert Q.check_caption_frames(v, props, None, (540, 960), "vertical", T, "both").status == Q.FAIL
    assert Q.check_caption_frames(v, props, None, (540, 960), "vertical", T, "youtube_shorts").status == Q.FAIL


# ---------------------------------------------------------------- abrupt endings and approval currency (M2b)
def test_abrupt_ending_detected_and_faded_ending_passes(tmp_path):
    T = Q.thresholds()
    loud = speechlike(3)                                   # never silent: the file stops mid-sound
    cut = build(tmp_path / "cut.mp4", ["A"], audio=loud)
    faded = loud.copy()
    faded[-48000:] *= np.linspace(1, 0, 48000, dtype=np.float32) ** 2
    ok = build(tmp_path / "ok.mp4", ["A"], audio=faded)
    assert status(Q.check_ending(cut, None, T), "abrupt ending") == [Q.FAIL]
    assert status(Q.check_ending(ok, None, T), "abrupt ending") == [Q.PASS]
    voice_cut = tmp_path / "v_cut.wav"
    sf.write(str(voice_cut), loud, 48000)
    voice_ok = tmp_path / "v_ok.wav"
    sf.write(str(voice_ok), np.concatenate([loud, np.zeros(9600, np.float32)]), 48000)
    assert status(Q.check_ending(ok, voice_cut, T), "narration ends cleanly") == [Q.FAIL]
    assert status(Q.check_ending(ok, voice_ok, T), "narration ends cleanly") == [Q.PASS]


def test_qc_output_fails_an_abrupt_ending_through_its_own_wiring(tmp_path):
    """V2 M7: qc_output itself must run the ending checks. A cut-off mix and a cut-off voice track have to come out
    of qc_output as FAIL (not as a missing check, and not as a guarded "could not run" error)."""
    item = tmp_path / "item"
    item.mkdir()
    loud = speechlike(3)
    cut = build(tmp_path / "cut.mp4", ["A"], audio=loud)
    voice_cut = tmp_path / "v_cut.wav"
    sf.write(str(voice_cut), loud, 48000)
    checks, _ = Q.qc_output(cut, size=SIZE, orient="vertical", voice=voice_cut, scenes=None, props=None, srt=None,
                            item=item, name="long")
    ending = [c for c in checks if c.name == "abrupt ending"]
    voice = [c for c in checks if c.name == "narration ends cleanly"]
    assert [c.status for c in ending] == [Q.FAIL] and "could not run" not in ending[0].detail
    assert [c.status for c in voice] == [Q.FAIL] and "could not run" not in voice[0].detail
    faded = loud.copy()
    faded[-48000:] *= np.linspace(1, 0, 48000, dtype=np.float32) ** 2
    ok = build(tmp_path / "ok.mp4", ["A"], audio=faded)
    checks, _ = Q.qc_output(ok, size=SIZE, orient="vertical", voice=None, scenes=None, props=None, srt=None,
                            item=item, name="long")
    assert [c.status for c in checks if c.name == "abrupt ending"] == [Q.PASS]


def test_approval_older_than_a_final_warns(tmp_path):
    import os
    item = tmp_path / "item"
    item.mkdir()
    assert Q.check_approval_current(item, False) is None
    (item / "long.mp4").write_bytes(b"x")
    m = item / ("APPR" + "OVED")          # fixture in a temp dir
    m.write_text("ok")
    os.utime(m, (1_000_000, 1_000_000))
    (item / "long.v2.mp4").write_bytes(b"y")
    c = Q.check_approval_current(item, False)
    assert c.status == Q.WARN and "long.v2.mp4" in c.detail
    os.utime(m, None)
    for p in item.glob("*.mp4"):
        os.utime(p, (1_000_000, 1_000_000))
    assert Q.check_approval_current(item, False).status == Q.PASS
    assert Q.check_approval_current(item, True) is None
