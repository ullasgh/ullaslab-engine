"""Packaging: versioned finals, captions, cost ledger, merged asset ledger, publishing pack."""
from __future__ import annotations
import json
import re
import shutil
from datetime import date
from pathlib import Path

from .captions import cues_to_srt

DISCLAIMER = "Education only. Not investment advice. Not SEBI/SEC registered. Data may be delayed. Do your own research."
AUDIO_MARK = "<!-- studio:audio-ledger -->"


def next_version_name(dirp: Path, stem: str, ext: str) -> Path:
    """long.mp4 if free, else long.v2.mp4, long.v3.mp4 ... Never returns an existing path."""
    first = dirp / f"{stem}{ext}"
    if not first.exists():
        return first
    ns = [int(m.group(1)) for p in dirp.glob(f"{stem}.v*{ext}") if (m := re.fullmatch(rf"{re.escape(stem)}\.v(\d+){re.escape(ext)}", p.name))]
    return dirp / f"{stem}.v{max(ns, default=1) + 1}{ext}"


def publish_file(src: Path, dirp: Path, stem: str, ext: str) -> Path:
    dst = next_version_name(dirp, stem, ext)
    shutil.copyfile(src, dst)
    return dst


def merge_assets_md(item: Path, audio: dict) -> None:
    """Append (replace) the music/SFX section of assets.md; the footage ledger above it is kept as written by broll fetch."""
    p = item / "assets.md"
    base = p.read_text(encoding="utf-8") if p.is_file() else "# Asset ledger\n"
    base = base.split(AUDIO_MARK)[0].rstrip() + "\n"
    lines = ["", AUDIO_MARK, "## Audio ledger", "", "| Use | Item | Source | Licence | Cost |", "|---|---|---|---|---|"]
    for out, m in audio.items():
        t = m["music"]
        src = t.get("source_url") or t["source"]
        lines.append(f"| music ({out}) | {t['title']} - {t['artist']} | {src} | [{t['licence']}]({t['licence_url']}) | $0 |")
    sfx = sorted({n for m in audio.values() for n in m["sfx"]})
    if sfx:
        lines.append(f"| sfx | {', '.join(sfx)} | generated in-house (ffmpeg lavfi) | CC0 1.0 (own work) | $0 |")
    lines += ["", "Narration: Chatterbox voice clone of the owner (synthetic voice, local). Music is never taken from the YouTube Audio Library.", ""]
    p.write_text(base + "\n".join(lines), encoding="utf-8")


def cost_md(item: Path, usage: dict) -> str:
    http = usage.get("broll", {})
    rows = [
        ("Remotion 4 (render)", "Free for individuals and orgs with up to 3 employees", f"local render, {usage.get('render_s', 0):.0f} s"),
        ("Headless Chrome (via Remotion)", "Free", "local"),
        ("ffmpeg / ffprobe", "Free (open source)", "local: clip prep, stems, ducking, loudnorm, mux"),
        (f"Word timings: {usage.get('asr', 'whisper')}", "Free, open weights (MIT); mlx-whisper locally, faster-whisper in CI", "local, no API"),
        ("Narration voice file", "Supplied by the pipeline (Chatterbox clone of the owner, free, MIT, local); the studio runs no TTS", "synthetic-voice flag stays ON"),
        ("Pixabay API / NASA Image Library / Wikimedia Commons", "Free; Pixabay 100 requests/min", f"{http.get('requests_used', 0)} requests, {http.get('cache_hits', 0)} cache hits"),
        ("Pexels API", "Free but off (key issuance paused)", "0 requests"),
        ("open_clip ranking (CPU)", "Free, MIT", "local"),
        ("Music: Pixabay Music or CC0 or generated pad", "Free licence, recorded in assets.md", "no purchase"),
        ("SFX", "Generated in-house (ffmpeg lavfi)", "no purchase"),
        ("AI B-roll provider", "Disabled", "0 calls"),
    ]
    out = ["# Cost ledger", "", f"Item: {item.name}  |  Generated: {date.today().isoformat()}", "",
           "| Tool | Free-tier limit / licence | Usage this run |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    out += ["", "**Total spend: $0.00** (no paid API, no GPU rental, no purchased assets).", ""]
    return "\n".join(out)


def _hook_title(output: dict) -> str:
    sc = output["scenes"][0]
    return (sc.get("on_screen_text") or sc["narration"]["text"]).strip().rstrip(".")


def _chart_sources(item: Path, doc: dict) -> list[str]:
    from .assemble import load_chart_specs, to_kit_chart
    refs = {sc["data_ref"]["ref"] for o in doc["outputs"] for sc in o["scenes"] if sc["type"] == "chart" and sc.get("data_ref")}
    specs, out = load_chart_specs(item), []
    for r in sorted(refs):
        try:
            m = to_kit_chart(r, specs[r])["meta"]
            out.append(f"{m['source']['name']} ({m['source']['as_of']}), tag {m['freshness']}")
        except Exception:
            pass
    return out


_BANNED = re.compile(r"\bmacro|(?<=[a-z])macro", re.I)  # owner rule 2026-11-09: never audience-facing


def publishing_pack(item: Path, doc: dict, meta: dict, assets: list[dict], audio: dict) -> str:
    longo = next((o for o in doc["outputs"] if o["output"] == "long"), doc["outputs"][0])
    titles = list(meta.get("title_options") or [])
    if meta.get("title"):
        titles.insert(0, meta["title"])
    titles = [t for t in titles if not _BANNED.search(t)]
    if not titles:
        titles = [_hook_title(longo), f"{_hook_title(longo)}: the economics explained", "An economics question, answered with data"]
    titles = [t for t in dict.fromkeys(t[:100] for t in titles) if not _BANNED.search(t)][:5]
    credits = sorted({(a.get("licence", {}).get("attribution") or f"{a.get('creator', '')} / {a.get('provider', '')}") for a in assets})
    music = sorted({f"Music: {m['music']['title']} - {m['music']['artist']} ({m['music']['licence']})" for m in audio.values()})
    tags = list(dict.fromkeys(["#economics", "#finance", "#markets", "#investingbasics", "#education"] + list(meta.get("hashtags") or [])))
    tags = [h for h in tags if not _BANNED.search(h)]
    L = ["# Publishing pack", "", f"Item: {item.name}", "", "## Title options", ""]
    L += [f"{i}. {t}" for i, t in enumerate(titles, 1)]
    for o in doc["outputs"]:
        if o["output"] != "long":
            L += ["", f"{o['output']} hook title: {_hook_title(o)}"]
    L += ["", "## Description (long)", "", DISCLAIMER, "", longo["scenes"][0]["narration"]["text"], ""]
    src = _chart_sources(item, doc)
    if src:
        L += ["Data sources:"] + [f"- {s}" for s in src] + [""]
    if credits or music:
        L += ["Credits:"] + [f"- {c}" for c in credits if c] + [f"- {m}" for m in music] + [""]
    L += ["Stock footage is illustrative and labelled on screen. Charts and maps are original animated graphics.", "",
          "## Hashtags", "", " ".join(tags), "", "## AI disclosure recommendation", "",
          "- Narration is a synthetic clone of the owner's voice: set the YouTube altered/synthetic content flag (containsSyntheticMedia) ON and the Instagram AI label ON.",
          "- Visuals are stock footage (labelled illustrative) and animated charts/maps; no realistic generated people or events.",
          "- Approval stays with the owner: nothing here is uploaded by the studio.", ""]
    return "\n".join(L)
