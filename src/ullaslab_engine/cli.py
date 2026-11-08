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
    if p.get("timing_url") and a.timing:
        eio.download(p["timing_url"], work / "timing_en.json", 5 * 1024 * 1024)
    load_bundle(work / "bundle")
    print("fetched")


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
    return 0 if qa["passed"] else 1


def cmd_upload(a):
    """PUT whichever known outputs exist for a language. Unknown/absent outputs are skipped."""
    p = _payload(a)
    work, lang, outs = Path(a.work), a.lang, p["outputs"]
    m = load_bundle(work / "bundle")
    items = [(f"audio_{lang}.wav", work / lang / "audio.wav", "audio/wav"),
             (f"captions_{lang}.srt", work / lang / "captions.srt", "application/x-subrip"),
             (f"captions_{lang}.vtt", work / lang / "captions.vtt", "text/vtt"),
             (f"qa_{lang}.json", work / lang / ("master/qa.json" if lang == m["source_lang"] else "qa.json"), "application/json")]
    if lang == m["source_lang"]:
        items += [("master.mp4", work / lang / "master" / "video.mp4", "video/mp4"),
                  ("timing_en.json", work / "timing_en.json", "application/json")]
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
        voice=dict(action="store_true"), timing=dict(action="store_true"))
    add("tts", cmd_tts, work=dict(required=True), lang=dict(required=True))
    add("captions", cmd_captions, work=dict(required=True), lang=dict(required=True), no_asr=dict(action="store_true"))
    add("render", cmd_render, work=dict(required=True), variant=dict(default=None))
    add("qa", cmd_qa, work=dict(required=True), lang=dict(required=True), variant=dict(default=None), no_asr=dict(action="store_true"))
    add("upload", cmd_upload, payload=dict(required=True), work=dict(required=True), lang=dict(required=True))
    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except (eio.TransferError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
