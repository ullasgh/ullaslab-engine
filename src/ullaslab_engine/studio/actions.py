"""WP8: the V2 studio render as a GitHub Actions job (render.yml `master`). Linux, CPU, headless.

work/                      (runner only; nothing here is uploaded except through `upload` to presigned R2 PUTs)
  bundle/                  manifest.json (+ `studio` block), charts/, studio/<files>  (fetched from the presigned bundle URL)
  voice.wav, clips/        the owner's reference and clips (presigned GETs; never logged, cached or uploaded)
  item/                    the studio queue item rebuilt from bundle/studio: scenes.json, meta.json, charts.resolved.json, ...
  logs/studio.log          everything the voice and studio steps print (script text can appear in errors): uploaded privately
                           as studio_log.txt, never printed to the public Actions log
  en/                      the outputs in the layout `upload` already knows (master/video.mp4, audio.wav, captions.*, qa)
  timing_en.json           the English segment windows on the master timeline, for the dub jobs and the story

Stages: prepare (bundle -> item), voice (one narration per output with the cloned voice, pace target), `studio run --asr
faster`, export (outputs + qa_en.json). qa_en.json keeps every engine gate, limits from config/quality.yaml unchanged: A1
(claim ids, chart hashes), A2 (data visuals), A3 (loudness, true peak, silence, wpm, sentence length, WER <= 3% against the
narrated text), A4 (voice-timed scene lengths and hook start; picture change from studio QC freezedetect), A5 (safe zone,
text sizes, contrast, word budget from a layout audit of every timed scene), duration, the studio QC verdict (any FAIL
fails) and, when the voice step refused the item, runner_budget."""
from __future__ import annotations
import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from ..audio import Wav, normalize_loudness
from ..bundle import load_bundle, seg_text
from ..config import quality
from ..qa import _check, _gate, gate_a1, gate_a3, gate_duration
from ..voice.delivery import NEUTRAL, TAGS, marker, strip_delivery
from ..voice.prosody import strip_markers
from . import FPS
from .qc import FAIL, latest_version

ITEM = "item"
OUTPUTS = ("long", "short", "reel")
LOG = Path("logs") / "studio.log"


class ActionsError(RuntimeError):
    pass


def jdump(obj, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def jload(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def studio_block(m: dict) -> dict:
    st = m.get("studio")
    if not st:
        raise ActionsError("bundle has no studio block: the content repo must send scenes.json (WP8 renders studio items only)")
    return st


def orientation_of(aspect: str) -> str:
    return "horizontal" if aspect == "16:9" else "vertical"


# ------------------------------------------------------------------ prepare
def prepare_item(work: Path) -> Path:
    """Copy bundle/studio/<files> into work/item and check scenes.json against the manifest's studio block."""
    work = Path(work)
    m = load_bundle(work / "bundle")
    st = studio_block(m)
    src, item = (work / "bundle" / "studio").resolve(), work / ITEM
    item.mkdir(parents=True, exist_ok=True)
    for f in st["files"]:
        p = (src / f).resolve()
        if src not in p.parents or not p.is_file():
            raise ActionsError(f"bundle studio/{f} missing")
        shutil.copy(p, item / f)
    if "scenes.json" not in st["files"]:
        raise ActionsError("bundle studio block lists no scenes.json")
    doc = jload(item / "scenes.json")
    if doc.get("schema_version") != 1 or not doc.get("outputs"):
        raise ActionsError("scenes.json: expected schema_version 1 with outputs[]")
    outs = [o["output"] for o in doc["outputs"]]
    if sorted(outs) != sorted(st["outputs"]) or len(set(outs)) != len(outs):
        raise ActionsError("scenes.json outputs differ from the manifest studio block")
    prim = next(o for o in doc["outputs"] if o["output"] == st["primary"]) if st["primary"] in outs else None
    if prim is None:
        raise ActionsError("primary output is not in scenes.json")
    if orientation_of(prim["aspect"]) != m["orientation"]:
        raise ActionsError("primary output aspect does not match the manifest orientation")
    return item


def install_music(work: Path, music_dir: Path | None = None) -> int:
    """Move fetched licensed music (work/music_lib/<file>) into the studio music folder; only ledger file names count.
    The studio checks each file's sha256 against config/music_ledger.yaml before using it."""
    from .audio import MUSIC_DIR, load_music_ledger
    music_dir = music_dir or MUSIC_DIR
    names = {t.get("file") for t in load_music_ledger()}
    n = 0
    lib = Path(work) / "music_lib"
    for p in sorted(lib.glob("*")) if lib.is_dir() else []:
        if p.name in names:
            music_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), music_dir / p.name)
            n += 1
    return n


# ------------------------------------------------------------------ voice
_LEAD_PACING = re.compile(r"^(?:\s*\[\[(?:hook|payoff|pause(?::\d+(?:\.\d+)?)?)\]\])*\s*")


def output_text(o: dict) -> str:
    """The narration of one output, scene by scene, as the director wrote it (pacing markup is kept for narrate()). When any
    scene carries `narration.delivery`, each scene's text is preceded by its delivery marker (`[[d:tag]]`, or `[[d:neutral]]`
    for an untagged scene between tagged ones), after any leading pacing marker; with no tag anywhere the text is exactly as
    before. The markers are never spoken or counted (prosody.strip_markers)."""
    scenes = [(sc.get("narration") or {}) for sc in o["scenes"]]
    tagged = any(n.get("delivery") for n in scenes)
    parts = []
    for n in scenes:
        t = n.get("text", "").strip()
        if not t:
            continue
        if tagged:
            tag = n.get("delivery") or NEUTRAL
            if tag != NEUTRAL and tag not in TAGS:
                raise ActionsError(f"scene narration.delivery {tag!r}: expected one of {', '.join(TAGS)}")
            lead = _LEAD_PACING.match(t).end()
            t = f"{t[:lead]}{marker(tag)} {t[lead:]}".strip()
        parts.append(t)
    return " ".join(parts)


def gate_words(text: str) -> int:
    """Words as the A3 wpm gate counts them (qa.gate_a3: whitespace tokens of the script text without pacing markers).
    The pacer fits to this count, so the number it controls is the number the gate measures."""
    return len(strip_markers(text).split())


# Synthesis seconds per second of speech, Chatterbox on the Actions runner's CPU (ubuntu-24.04, 4 vCPU): 11.6 on run
# 43172041796 (429 s for 37 s), 15.6 on run 43178997058 (641 s for 41 s, with the slow-down pacer). The slower figure,
# rounded up, so the guard is not optimistic. Used only to refuse, before any synthesis, an item that cannot finish.
RUNNER_RTF = 16.0


def voice_budget(doc: dict, wpm: float) -> dict | None:
    """Projected synthesis minutes for the distinct narrations of the item vs ULLASLAB_VOICE_BUDGET_MIN (unset = no limit,
    e.g. on the owner's Mac). Numbers only."""
    import os
    raw = os.environ.get("ULLASLAB_VOICE_BUDGET_MIN")
    if not raw:
        return None
    words = sum(len(strip_markers(t).split()) for t in {output_text(o) for o in doc["outputs"]})
    speech_min = words / max(wpm, 1.0)
    return {"words": words, "speech_min": round(speech_min, 1), "rtf": RUNNER_RTF,
            "projected_min": round(speech_min * RUNNER_RTF, 1), "budget_min": float(raw)}


def make_voices(work: Path, *, narrate_fn: Callable | None = None, lang: str = "en", log: Callable = print,
                attempt: int = 0) -> dict:
    """voice.<output>.wav for every output (identical narration is synthesised once). Clone reference: work/voice.wav (its
    sibling clips/clipN.wav win, per languages.yaml ref_clip). Returns numbers and engine names only."""
    if narrate_fn is None:
        from ..voice.narrate import narrate as narrate_fn
    work = Path(work)
    item = work / ITEM
    m = load_bundle(work / "bundle")
    st = studio_block(m)
    doc = jload(item / "scenes.json")
    ref = work / "voice.wav" if (work / "voice.wav").is_file() else None
    budget = voice_budget(doc, st.get("target_wpm") or 150)
    if budget:
        jdump({"outputs": {}, "budget": budget}, work / "voice_stats.json")
        log(f"voice budget: projected {budget['projected_min']} min of synthesis, budget {budget['budget_min']} min")
        if budget["projected_min"] > budget["budget_min"]:
            raise ActionsError(f"voice budget: projected {budget['projected_min']} min > {budget['budget_min']} min "
                               f"(render this item locally or raise the budget)")
    made: dict[str, str] = {}
    stats: dict[str, dict] = {}
    for o in doc["outputs"]:
        n = o["output"]
        text = output_text(o)
        if not text:
            raise ActionsError(f"output {n} has no narration")
        dst = item / f"voice.{n}.wav"
        if text in made:
            shutil.copy(item / f"voice.{made[text]}.wav", dst)
            stats[n] = {**stats[made[text]], "same_as": made[text]}
            continue
        t0 = time.time()
        overrides = {"pace": {"target_wpm": st["target_wpm"], "words": gate_words(text)}} if st.get("target_wpm") else None
        if attempt:   # a retry: a new deterministic seed (the chunk cache is keyed by seed, so attempt 1's audio is not replayed)
            overrides = {**(overrides or {}), "seed": retry_seed(lang, attempt)}
        w = narrate_fn(text, lang, ref, cache_dir=work / "tts_cache", overrides=overrides)
        w.save(dst)
        pace = (getattr(w, "meta", None) or {}).get("pace") or {}
        stats[n] = {"seconds": round(w.duration, 2), "synth_s": round(time.time() - t0, 1),
                    "rtf": round((time.time() - t0) / max(w.duration, 1e-6), 2), "engine": w.engine,
                    "wpm": pace.get("wpm"), "flags": len(w.flags), "clone_ref": ref is not None}
        made[text] = n
        log(f"voice {n}: {stats[n]['seconds']} s audio in {stats[n]['synth_s']} s, engine {w.engine}, wpm {stats[n]['wpm']}")
    jdump({"outputs": stats, **({"budget": budget} if budget else {})}, work / "voice_stats.json")
    return stats


VOICE_GATES = "voice_gates.json"
MAX_VOICE_ATTEMPTS = 3      # owner decision 2026-11-12: re-record up to 2 more times when ONLY the WER check fails
SEED_STEP = 1000            # attempt i uses seed base + i * SEED_STEP (chunk retries use +100, naturalness retry +1: no collision)
WER_ONLY = {("A3", "wer_pct")}


def retry_seed(lang: str, attempt: int) -> int:
    from ..voice.settings import voice_settings
    return int(voice_settings(lang).get("seed", 0)) + SEED_STEP * attempt


def _failed_checks(res: dict) -> set[tuple[str, str]]:
    return {(g, c["name"]) for g, v in res["gates"].items() for c in v["checks"] if not c["passed"]}


def _wer_of(res: dict):
    return next((c["value"] for c in res["gates"]["A3"]["checks"] if c["name"] == "wer_pct"), None)


def voice_phase(work: Path, *, narrate_fn: Callable | None = None, transcribe_fn: Callable | None = None,
                wer_fn: Callable | None = None, log: Callable = print, clock: Callable = time.time,
                max_attempts: int = MAX_VOICE_ATTEMPTS, _force_wer_fail: int = 0) -> dict:
    """PHASE 2 with the owner's retry rule. Attempt 1 as before. If the voice gates fail and the ONLY failing check is the
    A3 WER, narrate again with the next fixed seed and re-run the SAME gates (same limits), up to `max_attempts` in all; the
    first attempt that passes every voice gate is used and the render starts. Any other failing check, or every attempt
    failing WER, stops here (no render); a failing attempt is never picked as the best of. A retry only starts when the
    measured time of the last attempt still fits ULLASLAB_VOICE_BUDGET_MIN (unset = no limit). Public lines are
    `[voice-attempt] n=.. seed_index=.. wer_pct=.. PASS|FAIL` (numbers only); the WER diffs go to the private log.
    `_force_wer_fail` is a test-only hook (not reachable from the CLI, the workflow or the environment): the first N
    attempts report a failing WER."""
    import os
    work = Path(work)
    budget_min = float(os.environ.get("ULLASLAB_VOICE_BUDGET_MIN") or 0)
    t_start, attempts, res = clock(), [], None
    for i in range(max_attempts):
        t0 = clock()
        make_voices(work, narrate_fn=narrate_fn, log=log, attempt=i)
        w = wer_fn
        if i < _force_wer_fail:
            from ..asr import error_rate
            real = wer_fn or error_rate
            w = lambda r, h, l, real=real: max(real(r, h, l), 3.5)   # noqa: E731 - test hook only
        res = voice_gates(work, transcribe_fn=transcribe_fn, wer_fn=w, log=log)
        took = clock() - t0
        wer = _wer_of(res)
        attempts.append({"n": i + 1, "seed_index": i, "wer_pct": wer, "passed": res["passed"], "seconds": round(took, 1)})
        log(f"[voice-attempt] n={i + 1} seed_index={i} wer_pct={wer} {'PASS' if res['passed'] else 'FAIL'}")
        if res["passed"] or _failed_checks(res) != WER_ONLY or i + 1 >= max_attempts:
            break
        if budget_min and (clock() - t_start) + took > budget_min * 60:
            log(f"voice budget: retry skipped, {round((clock() - t_start) / 60, 1)} min used, "
                f"{round(took / 60, 1)} min needed, budget {budget_min:g} min")
            break
    res["attempts"] = attempts
    res["used"] = attempts[-1]["n"] if res["passed"] else None
    jdump(res, work / VOICE_GATES)
    return res


def voice_gates(work: Path, *, transcribe_fn: Callable | None = None, wer_fn: Callable | None = None,
                log: Callable = print) -> dict:
    """PHASE 2 (fail fast): the gates that depend on the voice track alone, evaluated right after synthesis and before the
    studio render starts: A3 (loudness, true peak, silence, wpm, sentence length, WER) and the duration limit, with the
    same functions and limits (config/quality.yaml) as the final QA. Writes work/voice_gates.json. A failure here costs the
    voice step only, not the 10-20 min render. Lines carry gate names and numbers only."""
    from ..asr import error_rate, transcribe, wer_diff
    transcribe_fn, wer_fn = transcribe_fn or transcribe, wer_fn or error_rate
    work = Path(work).resolve()
    m = load_bundle(work / "bundle")
    st = studio_block(m)
    src = m["source_lang"]
    doc = jload(work / ITEM / "scenes.json")
    prim = st["primary"]
    o = next(x for x in doc["outputs"] if x["output"] == prim)
    texts = [strip_markers((sc.get("narration") or {}).get("text", "")) for sc in o["scenes"]]
    texts = [t for t in texts if t]
    voice = work / ITEM / f"voice.{prim}.wav"
    wav = normalize_loudness(Wav.load(voice))
    words = transcribe_fn(voice, src)
    if not words:
        raise ActionsError("voice has no recognisable speech")
    pm = {"source_lang": src, "segments": [{"id": f"v{i}", "text": {src: t}} for i, t in enumerate(texts)]}
    tl = {"total_s": round(wav.duration, 3), "segments": [{"id": "v0", "start": round(words[0][1], 3),
                                                            "end": round(words[-1][2], 3)}], "scenes": [], "overruns": []}
    ref_text, hyp_text = " ".join(texts), " ".join(w[0] for w in words)
    gates = {"A3": gate_a3(pm, src, wav, tl, wer_fn(ref_text, hyp_text, src)),
             "duration": gate_duration(tl, orientation_of(o["aspect"]), None)}
    res = {"passed": all(g["passed"] for g in gates.values()), "gates": gates}
    jdump(res, work / VOICE_GATES)
    for d in wer_diff(ref_text, hyp_text, src):    # PRIVATE log only: these lines quote the script (the public step greps [voice-gate])
        log(f"[wer-diff] {d}")
    for g, v in gates.items():
        for c in v["checks"]:
            log(f"[voice-gate] {g}.{c['name']}={c['value']} limit={c['limit']} {'PASS' if c['passed'] else 'FAIL'}")
    return res


# ------------------------------------------------------------------ export
def srt_to_vtt(srt: str) -> str:
    import re
    body = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt.replace("\r\n", "\n"))
    return "WEBVTT\n\n" + body.lstrip("﻿")


def primary_timeline(scenes: list[dict], total_s: float) -> tuple[dict, dict]:
    """(pseudo manifest, timeline) for gate_a3 / gate_duration: one segment per narrated scene of the primary output,
    windows from the aligned words, total = the rendered video's length."""
    segs, tl = [], []
    for sc in scenes:
        n = sc.get("narration") or {}
        ws = n.get("words") or []
        text = strip_markers(n.get("text", ""))
        if not ws or not text:
            continue
        segs.append({"id": sc["id"], "text": {"en": text}})
        tl.append({"id": sc["id"], "start": round(ws[0]["start"], 3), "end": round(ws[-1]["end"], 3)})
    if not tl:
        raise ActionsError("primary output has no timed narration")
    return ({"source_lang": "en", "segments": segs},
            {"total_s": round(total_s, 3), "segments": tl, "scenes": [], "overruns": []})


def master_timing(m: dict, words: list, total_s: float) -> dict:
    """timing_en.json for the dub jobs and the story: the manifest's English segments (script.md VO lines) aligned to the
    primary output's ASR words, scene windows as the pre-V2 natural timeline had them, total = the master video length."""
    from ..synth import SR, _scene_windows
    from .timings import align, script_words
    allw, spans = [], []
    for s in m["segments"]:
        ws = script_words(strip_markers(seg_text(m, s, m["source_lang"])))
        spans.append((len(allw), len(allw) + len(ws)))
        allw += ws
    al = align(allw, [tuple(w) for w in words], 0.0, total_s)
    times: dict[str, tuple[float, float]] = {}
    prev = 0.0
    for s, (a, b) in zip(m["segments"], spans):
        times[s["id"]] = (al.times[a][0], al.times[b - 1][1]) if b > a else (prev, prev)
        prev = times[s["id"]][1]
    scenes, _ = _scene_windows(m, times)
    scenes = [sc for sc in scenes if sc["start"] < total_s - 0.05]
    for sc in scenes:
        sc["end"] = round(min(sc["end"], total_s), 3)
    if scenes:
        scenes[-1]["end"] = round(total_s, 3)
    return {"lang": m["source_lang"], "mode": "natural", "source": "studio", "total_s": round(total_s, 3), "sr": SR,
            "segments": [{"id": k, "start": round(a, 3), "end": round(min(b, total_s), 3)} for k, (a, b) in times.items()],
            "scenes": scenes, "overruns": [], "align_coverage": round(al.coverage, 4)}


def studio_qc_gate(qc: dict | None) -> dict:
    if qc is None:
        return _gate([_check("qc_report", "missing", "present", False)])
    checks = []
    for o, d in qc.get("outputs", {}).items():
        for c in d.get("checks", []):
            checks.append(_check(f"{o}.{c['group']}.{c['name']}", c["status"], "not FAIL", c["status"] != FAIL))
    for c in qc.get("item_checks", []):
        checks.append(_check(f"item.{c['group']}.{c['name']}", c["status"], "not FAIL", c["status"] != FAIL))
    checks.append(_check("verdict", qc.get("verdict"), "not FAIL", qc.get("verdict") != FAIL))
    return _gate(checks, "full report (with details) is studio_qc.json in the private bucket")


def pacing_gate(doc: dict, qc: dict | None) -> dict:
    """A4 (visual pacing) for studio renders, limits from quality.yaml A4_visual_pacing, on every output's timed scenes:
    the hook scene starts within hook_visual_within_s; every scene except the end-line (disclaimer) scene lasts
    scene_len_min_s..scene_len_max_s. Picture change: the pre-V2 templates counted planned animation beats; studio scenes
    move continuously, so the change limits are checked on the measured picture: studio QC's frozen-frame detection
    (ffmpeg freezedetect, fails at freeze_min_s = 2 s, below both max_seconds_between_changes and max_static_frame_s) must
    pass, and a scene the director marked `hold` (a deliberate still) may not last longer than max_static_frame_s."""
    q = quality()["A4_visual_pacing"]
    first, lens, holds = [], [], []
    for o in doc["outputs"]:
        sc = o["scenes"]
        if not sc:
            continue
        first.append(sc[0]["narration"].get("start_s") or 0.0)
        for i, x in enumerate(sc):
            n = x["narration"]
            if n.get("start_s") is None or n.get("end_s") is None:
                continue
            ln = n["end_s"] - n["start_s"]
            if x.get("role") != "disclaimer":
                lens.append(ln)
            if x.get("hold"):
                holds.append(ln)
    frozen = [c["status"] for d in ((qc or {}).get("outputs") or {}).values() for c in d.get("checks", [])
              if c.get("name") == "frozen frames"]
    freeze_ok = bool(frozen) and len(frozen) == len(doc["outputs"]) and all(st != FAIL for st in frozen)
    hold_max = max(holds, default=0.0)
    return _gate([
        _check("hook_visual_start_s", max(first, default=99.0), q["hook_visual_within_s"],
               bool(first) and max(first) <= q["hook_visual_within_s"]),
        _check("scene_len_min_s", min(lens, default=0.0), q["scene_len_min_s"], bool(lens) and min(lens) >= q["scene_len_min_s"]),
        _check("scene_len_max_s", max(lens, default=0.0), q["scene_len_max_s"], bool(lens) and max(lens) <= q["scene_len_max_s"]),
        _check("max_seconds_between_changes", "no frozen picture >= 2 s" if freeze_ok else "frozen picture found",
               q["max_seconds_between_changes"], freeze_ok),
        _check("max_static_frame_s", hold_max, q["max_static_frame_s"], freeze_ok and hold_max <= q["max_static_frame_s"]),
    ], "scene lengths from the voice-timed scenes of every output; picture change from studio QC freezedetect")


def safe_zone_gate(item: Path, doc: dict, audit_fn: Callable | None) -> dict:
    """A5 for studio renders: every timed scene of every output audited (safe_audit.py), A5 limits from quality.yaml."""
    from .safe_audit import audit_frames, check_audit, node_audit
    audit_fn = audit_fn or node_audit
    q = quality()["A5_mobile_readability"]
    tot = {"frames": 0, "scenes": 0, "outside": 0, "small_text": 0, "low_contrast": 0, "size_bad": 0, "fonts": 0, "font_missing": 0}
    min_cr, max_words = 99.0, 0
    for o in doc["outputs"]:
        n = o["output"]
        timed = [sc for sc in o["scenes"] if (sc.get("narration") or {}).get("start_s") is not None]
        tot["scenes"] += len(timed)
        pp = item / "work" / "final" / f"props.{n}.json"
        if not pp.is_file():
            tot["size_bad"] += 1
            continue
        props = jload(pp)
        frames = audit_frames(o["scenes"], int(props["durationInFrames"]))
        r = check_audit(audit_fn(pp, item / "work" / "final" / "public", frames, item / "work" / f"audit.{n}.json"),
                        orientation_of(o["aspect"]))
        for k in ("frames", "outside", "small_text", "low_contrast", "fonts", "font_missing"):
            tot[k] += r[k]
        tot["size_bad"] += 0 if r["size_ok"] else 1
        min_cr, max_words = min(min_cr, r["min_contrast"]), max(max_words, r["max_words"])
    checks = [_check("brand_font_loaded", tot["font_missing"] if tot["fonts"] else "no font data", 0,
                     tot["fonts"] > 0 and tot["font_missing"] == 0),
              _check("elements_outside_safe_zone", tot["outside"], 0, tot["outside"] == 0),
              _check("text_below_min_px", tot["small_text"], 0, tot["small_text"] == 0),
              _check("contrast_failures", tot["low_contrast"], 0, tot["low_contrast"] == 0),
              _check("min_contrast_ratio", min_cr, q["min_contrast_ratio"], min_cr >= q["min_contrast_ratio"]),
              _check("max_non_caption_words_per_scene", max_words, q["max_non_caption_words_per_scene"],
                     max_words <= q["max_non_caption_words_per_scene"]),
              _check("frames_audited", tot["frames"], tot["scenes"], tot["scenes"] > 0 and tot["frames"] >= tot["scenes"]),
              _check("frame_size", "ok" if not tot["size_bad"] else f"{tot['size_bad']} bad", "ok", not tot["size_bad"])]
    return _gate(checks, f"studio layout audit, one still per timed scene; text floors {q['min_body_text_px']}/"
                         f"{q['min_label_text_px']} px")


def export(work: Path, *, asr_wer: Callable | None = None, audit_fn: Callable | None = None) -> dict:
    """Copy the studio outputs into the upload layout and write qa_en.json. Always writes a qa file (a failed or partial
    studio run gives passed=false), so the private repo sees which gate broke. An unexpected error becomes a failed
    `export` gate carrying only the exception type; its message goes to the private log (it can quote script text)."""
    work = Path(work).resolve()   # the layout audit runs node in remotion/: paths must not be relative
    m = load_bundle(work / "bundle")
    try:
        qa = _export(work, m, asr_wer, audit_fn)
    except Exception as e:  # noqa: BLE001 - the public log gets the type only
        import traceback
        (work / LOG).parent.mkdir(parents=True, exist_ok=True)
        with open(work / LOG, "a", encoding="utf-8") as f:
            f.write("\n[export] " + traceback.format_exc())
        qa = _write_qa(m, {"export": _gate([_check("error", type(e).__name__, "none", False)])},
                       work / m["source_lang"] / "master" / "qa.json")
    sdir = work / m["source_lang"] / "studio"
    sdir.mkdir(parents=True, exist_ok=True)
    if (work / LOG).is_file():
        shutil.copy(work / LOG, sdir / "studio_log.txt")
    return qa


def _export(work: Path, m: dict, asr_wer: Callable | None, audit_fn: Callable | None) -> dict:
    from ..asr import error_rate
    asr_wer = asr_wer or error_rate
    item = work / ITEM
    st = studio_block(m)
    src = m["source_lang"]
    en, sdir = work / src, work / src / "studio"
    (en / "master").mkdir(parents=True, exist_ok=True)
    sdir.mkdir(parents=True, exist_ok=True)
    gates: dict[str, dict] = {"A1": gate_a1(m)}
    vg_p = work / VOICE_GATES
    va = jload(vg_p) if vg_p.is_file() else {}
    att = dict(attempts=va.get("attempts"), used=va.get("used"))
    if vg_p.is_file() and not jload(vg_p)["passed"]:   # phase 2 stopped the job before the render: report its gates
        gates.update(jload(vg_p)["gates"])
        return _write_qa(m, gates, en / "master" / "qa.json", **att)
    rc_p = work / "studio_rc"
    rc = int(rc_p.read_text().strip() or 1) if rc_p.is_file() else 1
    timed_p = item / "work" / "scenes.timed.json"
    prim = st["primary"]
    final = latest_version(item, prim, ".mp4")
    qc = jload(item / "qc.json") if (item / "qc.json").is_file() else None
    for name, dst in (("qc.json", "studio_qc.json"), ("publish.md", "studio_publish.md")):
        if (item / name).is_file():
            shutil.copy(item / name, sdir / dst)
    vs0 = jload(work / "voice_stats.json") if (work / "voice_stats.json").is_file() else {}
    if vs0.get("budget"):
        b = vs0["budget"]
        gates["runner_budget"] = _gate([_check("projected_voice_min", b["projected_min"], b["budget_min"],
                                               b["projected_min"] <= b["budget_min"])],
                                       f"Chatterbox on the runner at about {b['rtf']}x real time")
    gates["studio_run"] = _gate([_check("exit_code", rc, "0 or 1 (1 = QC FAIL)", rc in (0, 1)),
                                 _check("primary_final", "present" if final else "missing", "present", final is not None),
                                 _check("timings", "present" if timed_p.is_file() else "missing", "present", timed_p.is_file())])
    if not (final and timed_p.is_file()):
        gates["studio_qc"] = studio_qc_gate(qc)
        return _write_qa(m, gates, en / "master" / "qa.json", **att)
    doc = jload(timed_p)
    by = {o["output"]: o for o in doc["outputs"]}
    props = jload(item / "work" / "final" / f"props.{prim}.json")
    total = props["durationInFrames"] / FPS
    # ---- files in the upload layout
    shutil.copy(final, en / "master" / "video.mp4")
    voice = item / f"voice.{prim}.wav"
    wav = normalize_loudness(Wav.load(voice))
    wav.save(en / "audio.wav")
    srt = latest_version(item, f"captions.{prim}", ".srt")
    if srt:
        shutil.copy(srt, en / "captions.srt")
        (en / "captions.vtt").write_text(srt_to_vtt(srt.read_text(encoding="utf-8")), encoding="utf-8")
    for n in by:
        if n != prim:
            f = latest_version(item, n, ".mp4")
            if f:
                shutil.copy(f, sdir / f"studio_{n}.mp4")
            c = latest_version(item, f"captions.{n}", ".srt")
            if c:
                shutil.copy(c, sdir / f"studio_captions_{n}.srt")
        sheet = item / f"contact_sheet.{n}.png"
        if sheet.is_file():
            shutil.copy(sheet, sdir / f"studio_contact_sheet_{n}.png")
    th = latest_version(item, "thumb", ".png")
    if th:
        shutil.copy(th, sdir / "studio_thumb.png")
    words = jload(item / "work" / f"words.{prim}.json")
    timing = master_timing(m, words, total)
    jdump(timing, work / f"timing_{src}.json")
    jdump(timing, en / "timeline.json")   # the story stage reads the natural timeline from here
    vs = jload(work / "voice_stats.json") if (work / "voice_stats.json").is_file() else {"outputs": {}}
    pv = vs["outputs"].get(prim, {})
    jdump({"lang": src, "voice": True, "pipeline": "studio", "primary": prim, "engine": pv.get("engine"),
           "clone_ref": pv.get("clone_ref"), "wpm": pv.get("wpm"), "naturalness_flags": pv.get("flags", 0),
           "align_coverage": timing["align_coverage"]}, en / "status.json")
    # ---- gates (limits from config/quality.yaml, unchanged)
    pm, ptl = primary_timeline(by[prim]["scenes"], total)
    ref = " ".join(s["text"]["en"] for s in pm["segments"])
    hyp = " ".join(w[0] for w in words)
    gates["A2"] = _gate([_check("original_data_visuals", sum(1 for s in by[prim]["scenes"] if s.get("type") == "chart"),
                                quality()["A2_visual_storytelling"]["original_data_visual_min"],
                                sum(1 for s in by[prim]["scenes"] if s.get("type") == "chart")
                                >= quality()["A2_visual_storytelling"]["original_data_visual_min"])],
                        "chart scenes in the published (primary) output")
    gates["A3"] = gate_a3(pm, src, wav, ptl, asr_wer(ref, hyp, src))
    gates["A4"] = pacing_gate(doc, qc)
    gates["A5"] = safe_zone_gate(item, doc, audit_fn)
    gates["duration"] = gate_duration(ptl, m["orientation"], None)
    gates["studio_qc"] = studio_qc_gate(qc)
    return _write_qa(m, gates, en / "master" / "qa.json", **att)


def _write_qa(m: dict, gates: dict, path: Path, attempts: list | None = None, used=None) -> dict:
    qa = {"lang": m["source_lang"], "slug": m["slug"], "pipeline": "studio", "variant": "master",
          "passed": all(g["passed"] for g in gates.values()), "gates": gates}
    if attempts:   # how often the voice had to be re-recorded (numbers only): count, WER per attempt, the attempt used
        qa["voice_attempts"] = {"count": len(attempts), "wer_pct": [a["wer_pct"] for a in attempts], "used": used}
    jdump(qa, path)
    return qa


# ------------------------------------------------------------------ upload names
def studio_uploads(work: Path, lang: str) -> list[tuple[str, Path, str]]:
    """Extra files for `upload` (names start with studio_ so master.mp4 stays the first video in the review page)."""
    d = Path(work) / lang / "studio"
    types = {".mp4": "video/mp4", ".srt": "application/x-subrip", ".png": "image/png", ".json": "application/json",
             ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
    return [(p.name, p, types.get(p.suffix, "application/octet-stream")) for p in sorted(d.glob("studio_*")) if p.is_file()]
