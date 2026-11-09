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
def _item(tmp_path, chart_extra=None, meta=None, publish="# Pack\n\nEducation only. Not investment advice. Not SEBI/SEC registered. Data may be delayed. Do your own research.\n\n## AI disclosure recommendation\n"):
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
