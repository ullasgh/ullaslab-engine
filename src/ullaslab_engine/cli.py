"""Command line: python -m ullaslab_engine <command>. Never prints URLs or content."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from . import io as eio
from . import pipeline as P
from .bundle import load_bundle
from .config import language, languages


def _payload(a) -> dict:
    return eio.load_payload(Path(a.payload))


def cmd_mask(a):
    for line in eio.mask_lines(_payload(a)):
        print(line)


def _extras(code: str) -> str:
    cfg = language(code)
    engines = [e for e in (cfg["tts_engine"], cfg.get("fallback_engine")) if e and e != "none"]
    extras = {e.replace("indic_", "") for e in engines}
    if {"chatterbox", "parler"} <= extras:  # pinned dependency sets conflict: primary engine only
        extras.discard("parler")
    return ",".join(sorted(extras))


def cmd_plan(a):
    """Emit GitHub outputs: dub matrix (non-source languages), engine extras, has_dubs. No URLs."""
    p = _payload(a)
    rows = []
    for code in p["languages"]:
        cfg = language(code)
        if not cfg.get("dub"):
            continue
        rows.append({"lang": code, "extras": _extras(code)})
    print("matrix=" + json.dumps({"include": rows}))
    print("has_dubs=" + ("true" if rows else "false"))
    print("master_extras=" + _extras("en"))


def cmd_variants(a):
    m = load_bundle(Path(a.work) / "bundle")
    for v in m.get("variants", []):
        if v["lang"] == a.lang:
            print(v["name"])


def cmd_fetch(a):
    p = _payload(a)
    work = Path(a.work)
    z = eio.download(p["bundle_url"], work / "bundle.zip")
    eio.safe_unzip(z, work / "bundle")
    z.unlink()
    if p.get("voice_url") and a.voice:
        eio.download(p["voice_url"], work / "voice.wav", 50 * 1024 * 1024)
        # WP11: the three selected reference clips sit beside voice.wav (voice/clips/); ref_clip picks one per language
        for n, url in (p.get("voice_clip_urls") or {}).items():
            eio.download(url, work / "clips" / f"clip{n}.wav", 20 * 1024 * 1024)
    if p.get("music_url") and getattr(a, "music", False):  # WP14: optional story music bed (never logged)
        eio.download(p["music_url"], work / "music.bin", eio.MAX_MUSIC_BYTES)
    if p.get("timing_url") and a.timing:
        eio.download(p["timing_url"], work / "timing_en.json", 5 * 1024 * 1024)
    load_bundle(work / "bundle")
    print("fetched")


def cmd_fetch_model(a):
    """Download + verify + extract the mirrored Parler weights. Prints `hub=<dir>` (empty if none) for GITHUB_OUTPUT."""
    from .model import fetch_model
    hub = fetch_model(_payload(a), Path(a.dest))
    print(f"hub={hub or ''}")
    return 0


def cmd_tts(a):
    work = Path(a.work)
    m = load_bundle(work / "bundle")
    want_nat = any(v["lang"] == a.lang for v in m.get("variants", []))
    r = P.stage_tts(work, a.lang, want_natural=want_nat)
    if r["voice"]:
        print(f"rtf={r['rtf']}")  # synthesis seconds per audio second; numbers only
    print("voice" if r["voice"] else "captions-only")
    return 0


def cmd_captions(a):
    P.stage_captions(Path(a.work), a.lang, use_asr=not a.no_asr)
    return 0


def cmd_render(a):
    work = Path(a.work)
    m = load_bundle(work / "bundle")
    if a.variant:
        v = next(v for v in m["variants"] if v["name"] == a.variant)
        P.stage_render(work, v["lang"], v["name"], v["orientation"], natural=v["lang"] != m["source_lang"])
    else:
        P.stage_render(work, m["source_lang"], "master", m["orientation"])
    return 0


def cmd_story(a):
    """WP14: render story_<lang>.mp4 for a language that has story text. Best effort: a story failure never fails the Reel."""
    from . import story as ST
    work = Path(a.work)
    mp = work / "music.bin"
    qa = ST.stage_story(work, a.lang, mp if mp.exists() else None)
    if qa is None:
        print("no story for this language")
        return 0
    print("story", "PASS" if qa["passed"] else "FAIL", [c["name"] for c in qa["checks"] if not c["passed"]], "music" if qa["music"] else "no-music")
    return 0 if qa["passed"] else 1


def qa_lines(qa: dict) -> list[str]:
    """One line per check: gate.name=value limit=limit PASS|FAIL. Numbers and gate names only, never content."""
    return [f"{g}.{c['name']}={c['value']} limit={c['limit']} {'PASS' if c['passed'] else 'FAIL'}"
            for g, v in qa["gates"].items() for c in v["checks"]]


def cmd_qa(a):
    work = Path(a.work)
    m = load_bundle(work / "bundle")
    master_total = None
    if a.lang != m["source_lang"]:
        master_total = P.jload(work / "timing_en.json")["total_s"]
    if a.variant:
        v = next(v for v in m["variants"] if v["name"] == a.variant)
        qa = P.stage_qa(work, v["lang"], v["name"], v["orientation"], natural=v["lang"] != m["source_lang"], use_asr=not a.no_asr)
    elif a.lang == m["source_lang"]:
        qa = P.stage_qa(work, a.lang, "master", m["orientation"], use_asr=not a.no_asr)
    else:
        qa = P.stage_qa(work, a.lang, None, m["orientation"], use_asr=not a.no_asr, master_total=master_total)
    print("qa", "PASS" if qa["passed"] else "FAIL", [g for g, v in qa["gates"].items() if not v["passed"]])
    for line in qa_lines(qa):
        print(line)
    return 0 if qa["passed"] else 1


def cmd_upload(a):
    """PUT whichever known outputs exist for a language. Unknown/absent outputs are skipped."""
    p = _payload(a)
    work, lang, outs = Path(a.work), a.lang, p["outputs"]
    m = load_bundle(work / "bundle")
    items = [(f"audio_{lang}.wav", work / lang / "audio.wav", "audio/wav"),
             (f"captions_{lang}.srt", work / lang / "captions.srt", "application/x-subrip"),
             (f"captions_{lang}.vtt", work / lang / "captions.vtt", "text/vtt"),
             (f"status_{lang}.json", work / lang / "status.json", "application/json"),
             (f"qa_{lang}.json", work / lang / ("master/qa.json" if lang == m["source_lang"] else "qa.json"), "application/json")]
    if lang == m["source_lang"]:
        items += [("master.mp4", work / lang / "master" / "video.mp4", "video/mp4"),
                  ("timing_en.json", work / "timing_en.json", "application/json")]
    sdir = work / lang / "story"
    if (sdir / "qa.json").exists():  # WP14: the story file only ships when its own QA passed
        ok = json.loads((sdir / "qa.json").read_text()).get("passed")
        items += [(f"qa_story_{lang}.json", sdir / "qa.json", "application/json")]
        if ok:
            items += [(f"story_{lang}.mp4", sdir / "video.mp4", "video/mp4")]
    for v in m.get("variants", []):
        if v["lang"] == lang:
            items += [(f"{v['name']}.mp4", work / lang / v["name"] / "video.mp4", "video/mp4"),
                      (f"qa_{v['name']}.json", work / lang / v["name"] / "qa.json", "application/json")]
    n = 0
    for key, path, ctype in items:
        if key in outs and path.exists():
            eio.upload(outs[key], path, ctype)
            n += 1
    print(f"uploaded {n} files")
    return 0


def cmd_voice_analyze(a):
    import tempfile
    from .voice import prepare as V
    with tempfile.TemporaryDirectory() as t:
        w = V.load_any(Path(a.file), Path(t))
    r = V.analyze(w)
    print(json.dumps({"verdict": r.verdict, "metrics": r.metrics, "reasons": r.reasons, "notes": r.notes}, indent=1))
    return 0 if r.verdict != "RE_RECORD" else 1


def cmd_voice_prepare(a):
    """Local only. Writes ref.wav, clips/clip1..3.wav, qa.json (scalar metrics) under --out. Prints no audio data."""
    import tempfile
    from .voice import prepare as V
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        raw = V.load_any(Path(a.file), Path(t))
    qa = V.analyze(raw)
    clean = V.preprocess(raw, sr=a.sr)
    clean.save(out / "ref.wav")
    clips = V.select_clips(clean)
    V.write_clips(clean, clips, out / "clips")
    (out / "qa.json").write_text(json.dumps({"verdict": qa.verdict, "metrics": qa.metrics, "reasons": qa.reasons,
                                             "notes": qa.notes, "clips": clips}, indent=1))
    print(f"verdict={qa.verdict} clips={len(clips)} out={out}")
    for i, c in enumerate(clips, 1):
        print(f"clip{i}: {c['start']}-{c['end']}s score={c['total']}")
    return 0


def cmd_voice_demo(a):
    from .voice import demo as D
    from .voice.narrate import narrate
    idx = D.render_demo(Path(a.out), Path(a.refs) if a.refs else None, narrate,
                        langs=a.langs.split(",") if a.langs else None, max_per_lang=a.max_per_lang)
    print(f"demo written: {idx}")
    return 0


def cmd_voice_score(a):
    from .voice import naturalness as N
    from .audio import Wav
    r = N.score(Wav.load(Path(a.file)))
    print(json.dumps({"score": r.score, "passed": r.passed, "failures": r.failures, "metrics": r.metrics}, indent=1))
    return 0 if r.passed else 1


def cmd_broll_fetch(a):
    from .broll.run import run_fetch
    r = run_fetch(Path(a.scenes), Path(a.out), channel=a.channel, episode=a.episode, orientation=a.orientation,
                  cache_dir=Path(a.cache_dir) if a.cache_dir else None, force_fallback_ranker=a.fallback_ranker)
    ok = sum(1 for x in r["report"] if x["status"] == "ok")
    print(f"broll: {ok}/{len(r['report'])} scenes filled, {r['http'].used} requests, {r['http'].cache_hits} cache hits")
    for n in r["notes"]:
        print("note:", n)
    return 0 if ok == len(r["report"]) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ullaslab-engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **flags):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        for f, kw in flags.items():
            sp.add_argument("--" + f.replace("_", "-"), **kw)
        return sp

    add("mask", cmd_mask, payload=dict(required=True))
    add("plan", cmd_plan, payload=dict(required=True))
    add("variants", cmd_variants, work=dict(required=True), lang=dict(required=True))
    add("fetch", cmd_fetch, payload=dict(required=True), work=dict(required=True),
        voice=dict(action="store_true"), timing=dict(action="store_true"), music=dict(action="store_true"))
    add("tts", cmd_tts, work=dict(required=True), lang=dict(required=True))
    add("captions", cmd_captions, work=dict(required=True), lang=dict(required=True), no_asr=dict(action="store_true"))
    add("render", cmd_render, work=dict(required=True), variant=dict(default=None))
    add("story", cmd_story, work=dict(required=True), lang=dict(required=True))
    add("qa", cmd_qa, work=dict(required=True), lang=dict(required=True), variant=dict(default=None), no_asr=dict(action="store_true"))
    add("fetch-model", cmd_fetch_model, payload=dict(required=True), dest=dict(required=True))
    add("upload", cmd_upload, payload=dict(required=True), work=dict(required=True), lang=dict(required=True))
    add("voice-analyze", cmd_voice_analyze, file=dict(required=True))
    add("voice-prepare", cmd_voice_prepare, file=dict(required=True), out=dict(required=True), sr=dict(type=int, default=24000))
    add("voice-demo", cmd_voice_demo, out=dict(required=True), refs=dict(default=None), langs=dict(default=None),
        max_per_lang=dict(type=int, default=None))
    add("voice-score", cmd_voice_score, file=dict(required=True))
    bp = sub.add_parser("broll").add_subparsers(dest="broll_cmd", required=True)
    bf = bp.add_parser("fetch", help="fetch licensed stock footage for the footage scenes of a scenes.json")
    bf.set_defaults(fn=cmd_broll_fetch)
    bf.add_argument("--scenes", required=True)
    bf.add_argument("--out", required=True)
    bf.add_argument("--channel", default="default")
    bf.add_argument("--episode", default=None)
    bf.add_argument("--orientation", choices=["landscape", "portrait"], default=None, help="override; default per output aspect")
    bf.add_argument("--cache-dir", default=None)
    bf.add_argument("--fallback-ranker", action="store_true")
    sp = sub.add_parser("studio", help="video studio (timings, assembly, render, mix, package)").add_subparsers(dest="studio_cmd", required=True)
    sr = sp.add_parser("run", help="run the resumable stages for a queue item")
    sr.add_argument("item")
    sr.add_argument("--preview", action="store_true", help="half-resolution render first; writes preview/<output>.mp4")
    sr.add_argument("--until", choices=["timings", "broll", "assemble", "render", "mix", "package", "qc"], default="qc")
    sr.add_argument("--lang", default="en")
    sr.add_argument("--asr", choices=["auto", "mlx", "faster"], default="auto")
    sr.add_argument("--force", action="store_true", help="ignore checkpoints")
    sr.add_argument("--scene", action="append", metavar="ID",
                    help="re-render only the frame spans that show this scene (repeatable or comma separated) and rejoin; "
                         "the output gets a new version file")
    sr.add_argument("--output", choices=["long", "short", "reel"], default=None, help="limit --scene to one output")
    sr.add_argument("--no-scene-cache", action="store_true", help="render each output in one pass (no per-scene cache)")
    sr.set_defaults(fn=lambda a: __import__("ullaslab_engine.studio.run", fromlist=["x"]).cmd_studio_run(a))
    sq = sp.add_parser("qc", help="automated QC of a rendered queue item; writes qc.md, qc.json, contact sheets")
    sq.add_argument("item")
    sq.add_argument("--preview", action="store_true", help="check preview/<output>.mp4 (half size) instead of the finals")
    sq.add_argument("--platform", choices=["both", "youtube_shorts", "instagram_reels"], default="both",
                    help="safe-area template for vertical outputs: both = stricter of the two (default), or one platform")
    sq.set_defaults(fn=lambda a: __import__("ullaslab_engine.studio.qc", fromlist=["x"]).cmd_studio_qc(a))
    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except (eio.TransferError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
