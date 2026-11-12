"""WP8: the studio render as a GitHub Actions job (studio/actions.py, safe_audit.py, fixture.py, the payload contract and
the CLI glue). No models, no Remotion: synthesis, ASR, the layout audit and the studio run are faked; the real chain is
proven by the workflow_dispatch fixture run (docs/studio.md)."""
from __future__ import annotations
import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from ullaslab_engine import io as eio
from ullaslab_engine.bundle import load_bundle
from ullaslab_engine.config import ROOT
from ullaslab_engine.studio import actions as AC
from ullaslab_engine.studio import fixture as F
from ullaslab_engine.studio import safe_audit as SA
from ullaslab_engine.wer_norm import canonical_for_wer, words_to_digits
from conftest import speechlike

H = "https://acct.r2.cloudflarestorage.com/ullaslab-private/items/x/"


def payload(**extra) -> dict:
    p = {"job_id": "j0123456789abcdef0123", "bundle_url": H + "bundle.zip?X-Amz-Signature=a", "languages": ["en", "hi"],
         "timing_url": H + "out/en/timing_en.json?s=b", "outputs": {"master.mp4": H + "out/en/master.mp4?s=c",
                                                                    "studio_reel.mp4": H + "out/en/studio_reel.mp4?s=d"}}
    p.update(extra)
    return p


# ------------------------------------------------------------------ payload contract
def test_payload_schema_accepts_the_contract_and_studio_music():
    p = payload(studio={"music_urls": {"ambient-calm-atlasaudio-606216.mp3": H + "m.mp3?s=e"}})
    jsonschema.validate(p, json.loads((ROOT / "schema" / "payload.schema.json").read_text()))
    assert eio.validate_payload(p) is p
    assert eio.studio_music(p) == {"ambient-calm-atlasaudio-606216.mp3": H + "m.mp3?s=e"}
    masked = "\n".join(eio.mask_lines(p))
    assert H + "m.mp3?s=e" in masked   # studio music URLs are masked like every other URL


@pytest.mark.parametrize("bad", [
    {"studio": {"music_urls": {"../etc/passwd": H + "x"}}},           # path in a music name
    {"studio": {"music_urls": {"a.mp3": "https://evil.example.com/a.mp3"}}},  # host not allow-listed
    {"studio": {"other": 1}},                                          # unknown studio key
    {"unknown_prop": 1},                                               # not in the contract
])
def test_payload_rejects_bad_studio_fields_without_echoing_values(bad):
    with pytest.raises(eio.TransferError) as e:
        eio.validate_payload(payload(**bad))
    assert "evil" not in str(e.value) and "passwd" not in str(e.value) and "cloudflarestorage" not in str(e.value)


def test_payload_schema_caps_github_property_limit():
    s = json.loads((ROOT / "schema" / "payload.schema.json").read_text())
    assert s["maxProperties"] == 10 and len(s["properties"]) == 10 and s["additionalProperties"] is False


# ------------------------------------------------------------------ fixture and prepare
def test_fixture_bundle_is_valid_public_safe_and_inside_the_short_limits():
    m = F.manifest()
    assert m["studio"]["primary"] == "short" and m["orientation"] == "vertical"
    words = sum(len(t.split()) for t in F.NARRATION)
    assert 75 <= words <= 135          # 30-60 s at 150 wpm; the content repo's Short cap is 135 words
    assert F.NARRATION[-1].endswith("Follow UllasLab. Education only.")
    blob = json.dumps([m, F.scenes_doc(), F.chart()]).lower()
    assert "macro" not in blob and "synthetic" in blob
    jsonschema.validate(F.scenes_doc(), json.loads((ROOT / "tests/fixtures/scenes/scenes.schema.json").read_text()))
    assert F.chart()["chart_hash"]


def _bundle(work: Path, **studio) -> Path:
    b = work / "bundle"
    m = F.manifest()
    m["studio"].update(studio)
    AC.jdump(m, b / "manifest.json")
    AC.jdump(F.chart(), b / "charts" / "c1.json")
    AC.jdump(F.scenes_doc(), b / "studio" / "scenes.json")
    AC.jdump({"c1": F.chart()}, b / "studio" / "charts.resolved.json")
    AC.jdump({"title": "t", "synthetic_voice": True}, b / "studio" / "meta.json")
    (b / "studio" / "sources.md").write_text("| claim | tag |\n|---|---|\n| c1 | INFERRED |\n")
    load_bundle(b)
    return work


def test_prepare_item_copies_only_listed_files(tmp_path):
    w = _bundle(tmp_path)
    (w / "bundle" / "studio" / "stray.sh").write_text("echo no")
    item = AC.prepare_item(w)
    assert sorted(p.name for p in item.iterdir()) == sorted(F.manifest()["studio"]["files"])


@pytest.mark.parametrize("studio,msg", [({"primary": "long"}, "primary output is not in scenes.json"),
                                        ({"outputs": ["short"]}, "outputs differ")])
def test_prepare_item_refuses_a_mismatched_studio_block(tmp_path, studio, msg):
    w = _bundle(tmp_path, **studio)
    with pytest.raises(AC.ActionsError, match=msg):
        AC.prepare_item(w)


def test_prepare_item_refuses_wrong_orientation(tmp_path):
    w = _bundle(tmp_path)
    m = json.loads((w / "bundle" / "manifest.json").read_text())
    m["orientation"] = "horizontal"
    AC.jdump(m, w / "bundle" / "manifest.json")
    with pytest.raises(AC.ActionsError, match="orientation"):
        AC.prepare_item(w)


def test_bundle_without_studio_block_is_refused(tmp_path):
    w = _bundle(tmp_path)
    m = json.loads((w / "bundle" / "manifest.json").read_text())
    del m["studio"]
    AC.jdump(m, w / "bundle" / "manifest.json")
    with pytest.raises(AC.ActionsError, match="no studio block"):
        AC.prepare_item(w)


# ------------------------------------------------------------------ voice
def test_make_voices_one_synthesis_per_distinct_narration_with_clone_ref_and_pace(tmp_path):
    w = _bundle(tmp_path, target_wpm=150)
    AC.prepare_item(w)
    speechlike(3).save(w / "voice.wav")
    calls = []

    def fake(text, lang, ref, cache_dir=None, overrides=None):
        calls.append((text, lang, ref, overrides, cache_dir))
        x = speechlike(len(text.split()) / 2.5)
        x.engine = "chatterbox"
        x.meta = {"pace": {"wpm": 150.0}}
        return x

    st = AC.make_voices(w, narrate_fn=fake, log=lambda *_: None)
    assert len(calls) == 1          # short and reel share their narration
    text, lang, ref, ov, cache = calls[0]
    assert text == " ".join(F.NARRATION) and lang == "en" and ref == w / "voice.wav"
    # the pacer fits to the A3 gate's word count (whitespace tokens of the script), not to the spoken words
    assert ov == {"pace": {"target_wpm": 150, "words": len(text.split())}} and cache == w / "tts_cache"
    assert (w / "item" / "voice.short.wav").is_file() and (w / "item" / "voice.reel.wav").is_file()
    assert st["reel"]["same_as"] == "short" and st["short"]["clone_ref"] is True
    assert set(json.loads((w / "voice_stats.json").read_text())["outputs"]) == {"short", "reel"}


# ------------------------------------------------------------------ export
def _rendered(w: Path, *, qc_verdict="WARN", words=None, freeze="PASS"):
    """Lay down what `studio run` leaves behind for the fixture (finals, props, timed scenes, ASR words, qc.json)."""
    item = w / "item"
    doc = F.scenes_doc()
    t, words_out = 0.0, []
    for i, txt in enumerate(F.NARRATION):
        ws = []
        for tok in txt.split():
            ws.append({"w": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
            words_out.append([tok, round(t, 3), round(t + 0.3, 3)])
            t += 0.4
        for o in doc["outputs"]:
            n = o["scenes"][i]["narration"]
            n.update(words=ws, start_s=0.0 if i == 0 else ws[0]["start"])
        t += 0.3
    total = t + 0.6
    for o in doc["outputs"]:
        sc = o["scenes"]
        for k in range(len(sc)):
            sc[k]["narration"]["end_s"] = sc[k + 1]["narration"]["start_s"] if k + 1 < len(sc) else total
        AC.jdump({"durationInFrames": int(total * 30), "width": 1080, "height": 1920},
                 item / "work" / "final" / f"props.{o['output']}.json")
        (item / f"{o['output']}.mp4").write_bytes(b"mp4-" + o["output"].encode())
        (item / f"captions.{o['output']}.srt").write_text("1\n00:00:00,000 --> 00:00:01,500\nWhy\n")
        speechlike(total).save(item / f"voice.{o['output']}.wav")
    AC.jdump(doc, item / "work" / "scenes.timed.json")
    AC.jdump(words if words is not None else words_out, item / "work" / "words.short.json")
    (item / "thumb.png").write_bytes(b"png")
    qc = {"verdict": qc_verdict, "outputs": {o: {"checks": [{"group": "spec", "name": "video format", "status": "PASS",
                                                             "detail": "SCRIPT-TEXT-MUST-NOT-LEAK"},
                                                            {"group": "visual", "name": "frozen frames", "status": freeze,
                                                             "detail": "x"}]} for o in ("short", "reel")},
          "item_checks": [{"group": "data", "name": "chart hash vs ledger", "status": qc_verdict, "detail": "x"}]}
    AC.jdump(qc, item / "qc.json")
    (item / "publish.md").write_text("pack")
    (w / "studio_rc").write_text("0" if qc_verdict != "FAIL" else "1")
    return total


def _audit_ok(props, public, frames, out):
    return {"width": 1080, "height": 1920, "frames": [{"frame": f, "elements": [
        {"role": "headline", "x": 100, "y": 400, "w": 600, "h": 90, "fontPx": 68},
        {"role": "caption", "x": 100, "y": 1300, "w": 700, "h": 80, "fontPx": 44}]} for f in frames]}


def _ready(tmp_path, **kw):
    w = _bundle(tmp_path)
    AC.prepare_item(w)
    total = _rendered(w, **kw)
    (w / "logs").mkdir()
    (w / "logs" / "studio.log").write_text("private log")
    return w, total


def test_export_writes_the_upload_layout_and_a_passing_qa(tmp_path):
    w, total = _ready(tmp_path)
    qa = AC.export(w, asr_wer=lambda r, h, l: 1.0, audit_fn=_audit_ok)
    en = w / "en"
    assert qa["passed"], {g: v for g, v in qa["gates"].items() if not v["passed"]}
    assert set(qa["gates"]) == {"A1", "A2", "A3", "A4", "A5", "duration", "studio_run", "studio_qc"}
    assert (en / "master" / "video.mp4").read_bytes() == b"mp4-short"          # primary = master.mp4
    assert (en / "studio" / "studio_reel.mp4").read_bytes() == b"mp4-reel"
    assert not (en / "studio" / "studio_short.mp4").exists()                    # no duplicate of the master
    assert (en / "captions.vtt").read_text().startswith("WEBVTT") and "00:00:01.500" in (en / "captions.vtt").read_text()
    names = sorted(p.name for p in (en / "studio").iterdir())
    assert all(n.startswith("studio_") for n in names) and "studio_log.txt" in names and "studio_qc.json" in names
    assert min(names + ["master.mp4"]) == "master.mp4"   # the review page shows the first .mp4 by name: the master
    tl = json.loads((w / "timing_en.json").read_text())
    assert tl["total_s"] == round(int(total * 30) / 30, 3) and len(tl["segments"]) == len(F.NARRATION)
    assert tl["align_coverage"] == 1.0 and tl["segments"][0]["start"] == 0.0
    assert json.loads((en / "timeline.json").read_text()) == tl
    st = json.loads((en / "status.json").read_text())
    assert st["voice"] is True and st["pipeline"] == "studio" and st["primary"] == "short"
    pub = json.dumps(qa)
    assert "SCRIPT-TEXT-MUST-NOT-LEAK" not in pub   # qa holds statuses and numbers, QC details stay in studio_qc.json


def test_export_fails_on_wer_over_the_unchanged_limit(tmp_path):
    w, _ = _ready(tmp_path)
    qa = AC.export(w, asr_wer=lambda r, h, l: 3.5, audit_fn=_audit_ok)
    assert not qa["passed"] and not qa["gates"]["A3"]["passed"]
    wer = next(c for c in qa["gates"]["A3"]["checks"] if c["name"] == "wer_pct")
    assert wer["limit"] == 3 and not wer["passed"]


def test_export_fails_when_studio_qc_fails(tmp_path):
    w, _ = _ready(tmp_path, qc_verdict="FAIL")
    qa = AC.export(w, asr_wer=lambda r, h, l: 0.0, audit_fn=_audit_ok)
    assert not qa["passed"] and not qa["gates"]["studio_qc"]["passed"]


def test_export_fails_on_text_outside_the_safe_zone(tmp_path):
    w, _ = _ready(tmp_path)

    def outside(props, public, frames, out):
        a = _audit_ok(props, public, frames, out)
        a["frames"][0]["elements"].append({"role": "stamp", "x": 900, "y": 400, "w": 400, "h": 40, "fontPx": 36})
        return a
    qa = AC.export(w, asr_wer=lambda r, h, l: 0.0, audit_fn=outside)
    a5 = {c["name"]: c for c in qa["gates"]["A5"]["checks"]}
    assert not qa["passed"] and a5["elements_outside_safe_zone"]["value"] == 2   # one per output
    assert a5["frames_audited"]["passed"] and a5["frames_audited"]["limit"] == 12   # every timed scene of both outputs


def test_export_without_a_render_still_writes_a_failing_qa(tmp_path):
    w = _bundle(tmp_path)
    AC.prepare_item(w)
    qa = AC.export(w)
    assert not qa["passed"] and not qa["gates"]["studio_run"]["passed"]
    assert json.loads((w / "en" / "master" / "qa.json").read_text())["passed"] is False


def test_export_error_reaches_the_public_log_as_a_type_only(tmp_path):
    w, _ = _ready(tmp_path)

    def boom(*a):
        raise RuntimeError("remotion said: SCRIPT LINE ABOUT THE TOPIC")
    qa = AC.export(w, asr_wer=lambda r, h, l: 0.0, audit_fn=boom)
    assert not qa["passed"] and qa["gates"]["export"]["checks"][0]["value"] == "RuntimeError"
    assert "SCRIPT LINE" not in json.dumps(qa)
    assert "SCRIPT LINE" in (w / "en" / "studio" / "studio_log.txt").read_text()   # private log only


def test_master_timing_aligns_manifest_segments_and_clamps_to_the_video():
    m = F.manifest()
    m["source_lang"] = "en"
    words, t = [], 0.0
    for txt in F.NARRATION:
        for tok in txt.split():
            words.append([tok, t, t + 0.3])
            t += 0.4
    tl = AC.master_timing(m, words, 20.0)    # shorter than the speech: everything clamps to the video
    assert tl["total_s"] == 20.0 and all(s["end"] <= 20.0 for s in tl["segments"])
    assert tl["scenes"][-1]["end"] == 20.0 and tl["mode"] == "natural"


# ------------------------------------------------------------------ safe-zone audit
def test_check_audit_counts_text_outside_its_box_and_small_text():
    ok = {"width": 1080, "height": 1920, "frames": [{"frame": 1, "elements": [
        {"role": "headline", "x": 100, "y": 400, "w": 600, "h": 90, "fontPx": 68},
        {"role": "bg", "x": -50, "y": -50, "w": 2000, "h": 3000, "fontPx": 0}]}]}
    r = SA.check_audit(ok, "vertical")
    assert (r["outside"], r["small_text"], r["elements"], r["size_ok"]) == (0, 0, 1, True)
    bad = json.loads(json.dumps(ok))
    bad["frames"][0]["elements"] += [{"role": "body", "x": 100, "y": 10, "w": 300, "h": 40, "fontPx": 48},   # above the box
                                     {"role": "caption", "x": 100, "y": 1300, "w": 700, "h": 60, "fontPx": 30}]  # small
    r = SA.check_audit(bad, "vertical")
    assert r["outside"] == 1 and r["small_text"] == 1


def test_audit_floors_are_the_a5_limits():
    from ullaslab_engine.config import quality
    q = quality()["A5_mobile_readability"]
    f = SA.min_px()
    assert f["headline"] == f["caption"] == f["body"] == q["min_body_text_px"]
    assert f["stamp"] == f["tag"] == f["label"] == q["min_label_text_px"]


def test_check_audit_applies_a5_body_floor_contrast_and_word_budget():
    from ullaslab_engine.config import quality
    q = quality()["A5_mobile_readability"]
    el = lambda role, **k: {"role": role, "x": 100, "y": 400, "w": 600, "h": 60, "fontPx": 48, **k}
    r = SA.check_audit({"width": 1080, "height": 1920, "frames": [{"frame": 1, "elements": [
        el("body", fontPx=q["min_body_text_px"] - 4),                       # body under the A5 body floor
        el("label", fontPx=q["min_label_text_px"], words=4),                # label at its floor is fine
        el("headline", fg="#555555", bg="#4a4a4a", words=q["max_non_caption_words_per_scene"])]}]}, "vertical")
    assert r["small_text"] == 1 and r["low_contrast"] == 1 and r["min_contrast"] < q["min_contrast_ratio"]
    assert r["max_words"] == q["max_non_caption_words_per_scene"] + 4


def test_audit_frames_one_per_scene_inside_the_video():
    sc = [{"narration": {"start_s": 0.0, "end_s": 2.0}}, {"narration": {"start_s": 2.0, "end_s": 5.0}},
          {"narration": {"start_s": None, "end_s": None}}]
    assert SA.audit_frames(sc, 200) == [42, 123]     # 70% into each timed scene; untimed scenes are skipped
    assert SA.audit_frames(sc, 120) == [42, 119]     # clamped to the last frame


# ------------------------------------------------------------------ WER canonicalisation
@pytest.mark.parametrize("a,b", [("from one hundred to one hundred and twelve", "from 100 to 112"),
                                 ("four point two five percent", "4.25%"),
                                 ("two thousand and twenty six", "2026"),
                                 ("twenty five basis points", "25 bps"),
                                 ("one hundred and twelve", "100 and 12"),     # Whisper split the number (runner run)
                                 ("2026", "2000 26")])
def test_spelled_and_written_numbers_compare_equal(a, b):
    assert canonical_for_wer(a) == canonical_for_wer(b)


def test_words_to_digits_leaves_other_words_and_splits_malformed_runs():
    assert words_to_digits("the rate rose".split()) == ["the", "rate", "rose"]
    assert words_to_digits("twenty twenty six".split()) == ["20", "26"]
    assert words_to_digits("one hundred and twelve and more".split()) == ["112", "and", "more"]
    assert words_to_digits("10 5 and 100 and 1000".split()) == ["10", "5", "and", "100", "and", "1000"]   # not one number


def test_wer_counts_a_real_word_error_after_canonicalisation():
    from ullaslab_engine.asr import error_rate
    assert error_rate("it rose from one hundred to one hundred and twelve", "it rose from 100 to 112", "en") == 0.0
    assert error_rate("it rose from one hundred to one hundred and twelve", "it fell from 100 to 112", "en") > 0


def test_asr_prompt_spells_the_sign_off_brand():
    from ullaslab_engine import asr
    assert "UllasLab" in asr._PROMPT and "Education only." in asr._PROMPT


# ------------------------------------------------------------------ CLI glue
def test_upload_sends_studio_files_only_when_the_payload_names_them(tmp_path, monkeypatch):
    from ullaslab_engine import cli
    w, _ = _ready(tmp_path)
    AC.export(w, asr_wer=lambda r, h, l: 0.0, audit_fn=_audit_ok)
    p = payload()
    pf = tmp_path / "event.json"
    pf.write_text(json.dumps({"client_payload": p}))
    sent = []
    monkeypatch.setattr(eio, "upload", lambda url, path, ctype: sent.append((url, Path(path).name, ctype)))
    assert cli.main(["upload", "--payload", str(pf), "--work", str(w), "--lang", "en"]) == 0
    assert sorted(n for _, n, _ in sent) == ["studio_reel.mp4", "video.mp4"]
    assert dict((n, c) for _, n, c in sent)["studio_reel.mp4"] == "video/mp4"


def test_upload_puts_qa_files_last(tmp_path, monkeypatch):
    """The private poll treats qa_<lang>.json as the end of the render: every video must already be in R2."""
    from ullaslab_engine import cli
    w, _ = _ready(tmp_path)
    AC.export(w, asr_wer=lambda r, h, l: 0.0, audit_fn=_audit_ok)
    names = ["master.mp4", "qa_en.json", "studio_reel.mp4", "captions_en.srt", "audio_en.wav", "timing_en.json",
             "status_en.json", "studio_qc.json"]
    p = payload(outputs={n: H + n + "?s=x" for n in names})
    pf = tmp_path / "event.json"
    pf.write_text(json.dumps({"client_payload": p}))
    order = []
    monkeypatch.setattr(eio, "upload", lambda url, path, ctype: order.append(url.split("/")[-1].split("?")[0]))
    assert cli.main(["upload", "--payload", str(pf), "--work", str(w), "--lang", "en"]) == 0
    assert order[-1] == "qa_en.json" and "master.mp4" in order and len(order) == len(names)


def test_plan_fixture_has_no_dubs(capsys):
    from ullaslab_engine import cli
    assert cli.main(["plan", "--fixture"]) == 0
    out = capsys.readouterr().out
    assert "has_dubs=false" in out and '"include": []' in out and "master_extras=" in out


def test_fetch_studio_downloads_music_by_ledger_name(tmp_path, monkeypatch):
    from ullaslab_engine import cli
    w = _bundle(tmp_path / "w")
    zipdir = tmp_path / "z"
    shutil.make_archive(str(zipdir), "zip", w / "bundle")
    got = []

    def dl(url, dest, max_bytes=0):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.name == "bundle.zip":
            shutil.copy(str(zipdir) + ".zip", dest)
        else:
            dest.write_bytes(b"x")
        got.append(dest.relative_to(tmp_path / "out").as_posix())
        return dest
    monkeypatch.setattr(eio, "download", dl)
    p = payload(studio={"music_urls": {"ambient-calm-atlasaudio-606216.mp3": H + "m.mp3?s=e"}})
    pf = tmp_path / "event.json"
    pf.write_text(json.dumps({"client_payload": p}))
    assert cli.main(["fetch", "--payload", str(pf), "--work", str(tmp_path / "out"), "--studio"]) == 0
    assert "music_lib/ambient-calm-atlasaudio-606216.mp3" in got


def test_install_music_moves_only_ledger_files(tmp_path):
    lib = tmp_path / "music_lib"
    lib.mkdir()
    (lib / "ambient-calm-atlasaudio-606216.mp3").write_bytes(b"a")
    (lib / "not-in-ledger.mp3").write_bytes(b"b")
    dst = tmp_path / "music"
    assert AC.install_music(tmp_path, dst) == 1
    assert [p.name for p in dst.iterdir()] == ["ambient-calm-atlasaudio-606216.mp3"]


def test_music_fetch_off_never_calls_r2_or_wrangler(tmp_path):
    from ullaslab_engine.studio import audio as A
    calls = []
    led = [{"id": "t1", "file": "t1.mp3", "sha256": "0" * 64}]
    r = A.fetch_missing_tracks(led, tmp_path, env={"ULLASLAB_MUSIC_FETCH": "off"}, getter=lambda *a: calls.append(a))
    assert calls == [] and r["fetched"] == [] and "fetch off" in r["failed"]["t1"]


def test_layout_audit_hands_node_absolute_paths(tmp_path, monkeypatch):
    """Regression (first Actions fixture run): node runs with cwd=remotion/, so a relative work dir broke the audit."""
    import subprocess
    seen = {}

    def fake_run(cmd, cwd=None, capture_output=True, text=True):
        seen["cmd"] = cmd
        Path(cmd[cmd.index("--audit-out") + 1]).write_text('{"width": 1080, "height": 1920, "frames": []}')
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(SA.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "w").mkdir()
    SA.node_audit(Path("w/props.json"), Path("w/public"), [1], Path("w/a.json"))
    for flag in ("--props", "--public", "--audit-out"):
        assert Path(seen["cmd"][seen["cmd"].index(flag) + 1]).is_absolute(), flag


def _doc(lengths, hold=None):
    t, sc = 0.0, []
    for i, ln in enumerate(lengths):
        sc.append({"id": f"s{i + 1:02d}", "role": "disclaimer" if i == len(lengths) - 1 else "hook" if i == 0 else "setup",
                   "narration": {"start_s": t, "end_s": t + ln}, **({"hold": True} if hold == i else {})})
        t += ln
    return {"outputs": [{"output": "short", "aspect": "9:16", "scenes": sc}]}


QC_OK = {"outputs": {"short": {"checks": [{"name": "frozen frames", "status": "PASS"}]}}}


def test_a4_pacing_passes_voice_timed_scenes_inside_the_limits():
    g = AC.pacing_gate(_doc([3, 6, 11.5, 1.0]), QC_OK)       # the end-line scene may be short
    assert g["passed"], g


@pytest.mark.parametrize("doc,qc,failing", [
    (_doc([3, 12.5, 4]), QC_OK, "scene_len_max_s"),
    (_doc([1.5, 6, 4]), QC_OK, "scene_len_min_s"),
    (_doc([3, 6, 4]), {"outputs": {"short": {"checks": [{"name": "frozen frames", "status": "FAIL"}]}}}, "max_seconds_between_changes"),
    (_doc([3, 6, 4]), None, "max_seconds_between_changes"),               # no QC evidence is a fail, not a pass
    (_doc([3, 6, 4], hold=1), QC_OK, "max_static_frame_s"),              # a deliberate still over 5 s
])
def test_a4_pacing_fails_each_limit(doc, qc, failing):
    g = AC.pacing_gate(doc, qc)
    assert not g["passed"] and failing in [c["name"] for c in g["checks"] if not c["passed"]]


def test_voice_budget_refuses_before_any_synthesis_and_export_names_the_gate(tmp_path, monkeypatch):
    w = _bundle(tmp_path, target_wpm=150)
    AC.prepare_item(w)
    monkeypatch.setenv("ULLASLAB_VOICE_BUDGET_MIN", "1")     # 106 words at 150 wpm x 16 = 11.3 min > 1
    called = []
    with pytest.raises(AC.ActionsError, match="voice budget"):
        AC.make_voices(w, narrate_fn=lambda *a, **k: called.append(1), log=lambda *_: None)
    assert called == []
    qa = AC.export(w)
    g = qa["gates"]["runner_budget"]
    assert not qa["passed"] and not g["passed"] and g["checks"][0]["value"] == 11.3


def test_voice_budget_off_without_the_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ULLASLAB_VOICE_BUDGET_MIN", raising=False)
    assert AC.voice_budget(F.scenes_doc(), 150) is None
    monkeypatch.setenv("ULLASLAB_VOICE_BUDGET_MIN", "60")
    b = AC.voice_budget(F.scenes_doc(), 150)
    assert b["words"] == 106 and b["projected_min"] <= b["budget_min"]   # short and reel share one narration
    assert b["rtf"] == AC.RUNNER_RTF >= 15.6     # never below the slowest runner rate measured (run 43178997058)


# ------------------------------------------------------------------ live QA fixes (2026-11-12)
def test_gate_words_counts_like_gate_a3_and_not_like_the_spoken_words():
    from ullaslab_engine.voice.narrate import _words
    from ullaslab_engine.voice.textnorm import normalize_text
    t = "It was 4.95 percent on November 3rd, [[pause:0.5]] and 4.88 on 10-year bonds."
    assert AC.gate_words(t) == 12          # whitespace tokens without the marker
    spoken = _words(normalize_text("It was 4.95 percent on November 3rd, and 4.88 on 10-year bonds.", "en"), "en")
    assert spoken > AC.gate_words(t) + 4   # numbers verbalise to several words: the old pacer count


def test_pacer_fits_the_gate_word_count_so_a_number_heavy_script_is_not_read_too_slowly():
    import numpy as np
    from ullaslab_engine.voice import narrate as N
    sr = 24000
    chunks = [np.ones(int(sr * 6.0), dtype=np.float32) * 0.1 for _ in range(4)]   # 24 s of speech
    pauses, keep = [0.4] * 4, [False] * 4
    pace = dict(N.PACE_DEFAULTS)
    # 40 gate words in 25.6 s is 94 wpm: the pacer must shorten to 150 wpm (16 s) as far as its caps allow
    _, _, old = N.fit_pace(chunks, pauses, keep, 40 * 2, sr, pace)      # the old count: 80 spoken words
    _, _, new = N.fit_pace(chunks, pauses, keep, 40, sr, pace)
    assert old["raw_wpm"] > new["raw_wpm"]            # the old count flattered the raw rate by the verbalisation factor
    assert new["speedup"] == pace["max_speedup"]      # and the true rate needs the full speed-up
    assert pace_words_override_reaches_once()


def pace_words_override_reaches_once():
    from ullaslab_engine.voice import narrate as N
    assert N.pace_settings("en", {"pace": {"target_wpm": 150, "words": 125}})["words"] == 125
    return N.pace_settings("en")["words"] == 0


SIGN_OFF = "Follow UllasLab. Education only."


@pytest.mark.parametrize("heard", ["Follow Ulos' lab, education only.", "Follow Ullas lab. Education only.", "Follow Ullis Lab education only",
                                   "follow Ula s lab, education only", "Follow Ula's lab. Education only.", "Follow Ulaslab. Education only.",
                                   "Follow Ola's lab education only", "Follow Ullah slab. Education only."])
def test_the_lexicon_name_is_accepted_in_every_spelling_the_asr_gives_it(heard):
    """The brand is a proper name no ASR can spell; its entry in config/lexicon.yaml carries `name: true`."""
    from ullaslab_engine.asr import error_rate
    assert error_rate(SIGN_OFF, heard, "en") == 0.0


@pytest.mark.parametrize("heard", ["Follow us lab. Education only.", "Follow Alice lab. Education only.", "Follow Wallace lab. Education only.",
                                   "Follow Ellis club. Education only.", "Follow Ullas laugh. Education only.", "Follow all. Education only.",
                                   "Follow Ulysses lab. Education only."])
def test_near_miss_words_are_not_absorbed_into_the_name(heard):
    from ullaslab_engine.asr import error_rate
    assert error_rate(SIGN_OFF, heard, "en") > 0


@pytest.mark.parametrize("heard", ["Follow Google lab. Education only.", "Follow Ulysses. Education only.", "Follow us. Education only.",
                                   "Follow Ullas lab. Education on.", "Follow Ullas lab education only now", "Follow the lab. Education only."])
def test_other_words_around_the_name_still_count_as_errors(heard):
    from ullaslab_engine.asr import error_rate
    assert error_rate(SIGN_OFF, heard, "en") > 0


def test_names_come_from_the_lexicon_not_from_code(tmp_path, monkeypatch):
    from ullaslab_engine import wer_norm as W
    assert W.proper_names("en") == ["ullaslab"]
    lex = tmp_path / "lex.yaml"
    lex.write_text('version: 1\ncommon:\n  - {match: "UllasLab", say: "Ullas Lab"}\n')
    monkeypatch.setenv("ULLASLAB_LEXICON", str(lex))
    assert W.proper_names("en") == []
    from ullaslab_engine.asr import error_rate
    assert error_rate(SIGN_OFF, "Follow Ulos lab. Education only.", "en") > 0       # no `name: true`, no leniency


def test_wer_diff_lists_the_differing_tokens_for_the_private_log():
    from ullaslab_engine.asr import wer_diff
    d = wer_diff("It was 4.95 percent on the day. " + SIGN_OFF, "It was 4.95 percent percent on the day. Follow Ula's lab. Education on.", "en")
    assert d == ["I ->percent", "S only->on"]
    assert wer_diff("a b c", "a b c", "en") == []


def test_voice_gate_and_final_qa_compute_wer_through_the_same_function(tmp_path, monkeypatch):
    """One implementation: the runner's voice gate (phase 2) and the final QA (phase 4) both call asr.error_rate."""
    from ullaslab_engine import asr
    calls = []
    real = asr.error_rate
    monkeypatch.setattr(asr, "error_rate", lambda r, h, l: (calls.append(("rate", r, h)), real(r, h, l))[1])
    w, words = _voiced(tmp_path, secs=42.0)
    AC.voice_gates(w, transcribe_fn=lambda p, l: words, log=lambda *_: None)
    w2, _ = _ready(tmp_path / "second")
    AC.export(w2, audit_fn=_audit_ok)
    assert len(calls) == 2 and all(c[0] == "rate" for c in calls)


def _voiced(tmp_path, wpm_words=None, secs=None):
    w = _bundle(tmp_path)
    AC.prepare_item(w)
    text = " ".join(F.NARRATION)
    n = len(text.split())
    dur = secs if secs is not None else n / 150 * 60 + 0.6
    for o in ("short", "reel"):
        speechlike(dur).save(w / "item" / f"voice.{o}.wav")
    words = [(t, 0.3 + i * (dur - 0.6) / n, 0.3 + (i + 0.9) * (dur - 0.6) / n) for i, t in enumerate(text.split())]
    return w, words


def test_voice_gates_pass_at_target_pace_and_write_numbers_only(tmp_path):
    w, words = _voiced(tmp_path, secs=42.0)
    lines = []
    res = AC.voice_gates(w, transcribe_fn=lambda p, l: words, wer_fn=lambda r, h, l: 1.0, log=lines.append)
    a3 = {c["name"]: c for c in res["gates"]["A3"]["checks"]}
    assert res["passed"] and 135 <= a3["wpm"]["value"] <= 175 and a3["wer_pct"]["limit"] == 3
    assert res["gates"]["duration"]["checks"][0]["limit"] == "30.0-60.0"
    assert (w / "voice_gates.json").is_file()
    assert lines and all(l.startswith("[voice-gate] ") and l.endswith(("PASS", "FAIL")) for l in lines)


@pytest.mark.parametrize("secs,wer,failing", [(120.0, 1.0, {"A3", "duration"}), (42.0, 3.01, {"A3"}), (62.0, 1.0, {"A3", "duration"})])
def test_voice_gates_fail_each_unchanged_limit_before_the_render(tmp_path, secs, wer, failing):
    w, words = _voiced(tmp_path, secs=secs)
    res = AC.voice_gates(w, transcribe_fn=lambda p, l: words, wer_fn=lambda r, h, l: wer, log=lambda *_: None)
    assert {g for g, v in res["gates"].items() if not v["passed"]} == failing and not res["passed"]


def test_export_reports_the_voice_gate_failure_without_a_render(tmp_path):
    w, words = _voiced(tmp_path, secs=42.0)
    (w / "logs").mkdir()
    (w / "logs" / "studio.log").write_text("private")
    AC.voice_gates(w, transcribe_fn=lambda p, l: words, wer_fn=lambda r, h, l: 3.5, log=lambda *_: None)
    qa = AC.export(w)
    assert not qa["passed"] and not qa["gates"]["A3"]["passed"] and "studio_run" not in qa["gates"]
    assert json.loads((w / "en" / "master" / "qa.json").read_text())["passed"] is False


def test_studio_voice_command_fails_when_a_voice_gate_fails(tmp_path, monkeypatch):
    from ullaslab_engine import cli
    monkeypatch.setattr(AC, "make_voices", lambda *a, **k: {})
    monkeypatch.setattr(AC, "voice_gates", lambda *a, **k: {"passed": False, "gates": {"A3": {"passed": False, "checks": []}}})
    assert cli.cmd_studio_voice(type("A", (), {"work": str(tmp_path)})()) == 1


def test_chart_stamp_drops_the_freshness_tag_before_it_is_drawn():
    """Live run 2026-11-12: the content stamp ended with '[RECENT]' and studio QC (no freshness labels on screen) failed."""
    from ullaslab_engine.studio import assemble as A
    c = F.chart()
    c["source"] = {"name": "Source: FRED, St. Louis Fed, DGS10. As of 2026-11-09. [RECENT]", "as_of": "2026-11-09"}
    k = A.to_kit_chart("c1", c)
    assert k["meta"]["source"]["name"] == "Source: FRED, St. Louis Fed, DGS10. As of 2026-11-09."
    assert k["meta"]["freshness"] == c.get("freshness", "RECENT")           # the tag stays in the data
    assert A.stamp_name("Source: x [LAGGED]") == "Source: x" and A.stamp_name("Source: [x] plan") == "Source: [x] plan"


def test_voice_gate_writes_the_wer_diff_to_the_private_log_only(tmp_path):
    import re
    w, words = _voiced(tmp_path, secs=42.0)
    words = list(words)
    words[3] = ("SECRETWORD", *words[3][1:])
    lines = []
    AC.voice_gates(w, transcribe_fn=lambda p, l: words, log=lines.append)
    diff = [l for l in lines if l.startswith("[wer-diff] ")]
    assert diff and any("SECRETWORD".lower() in l.lower() for l in diff)
    public = re.compile(r"^\[voice-gate\] [A-Za-z0-9_]+\.[a-z_]+=[-0-9.a-z_]+ limit=[-0-9.a-zA-Z_ +]+ (PASS|FAIL)$|^voice (gates|budget)")
    assert not any(public.match(l) for l in diff)        # the workflow prints only lines matching this
    assert not any("secretword" in l.lower() for l in lines if public.match(l))
