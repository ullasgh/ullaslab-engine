"""WP8 synthetic studio item for the `workflow_dispatch` proof run of render.yml (and local checks).

Public-safe by construction: generic education text written for this repo, a chart of made-up numbers labelled as such,
generated test-pattern footage (CC0, own work), and a reference voice synthesised with the Kokoro stock voice (Apache-2.0)
so the Chatterbox clone path runs without anybody's real voice. Nothing here comes from the private content repo."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from ..broll.ledger import sha256_file, write_ledger
from ..qa import chart_hash
from .actions import ITEM, jdump, prepare_item
from .pack import DISCLAIMER

SLUG = "fixture-studio-short"
NARRATION = [
    "Why does money saved today buy a little less every year?",
    "When prices rise across the economy, each unit of currency stretches across fewer goods, so the same note buys a smaller basket.",
    "This made up chart shows a price index climbing from one hundred to one hundred and twelve over three years.",
    "Savings that earn less than that climb lose buying power, while savings that keep pace hold their ground.",
    "Economists call the gap between the two the real return, and it is worth checking before comparing any two options.",
    "So next time a number looks large, ask what it buys. Follow UllasLab. Education only.",
]
ROLES = ["hook", "setup", "evidence", "mechanism", "consequence", "disclaimer"]
# One `flow` scene that carries a data_point ref but has no visual_data.json entry: the shape the live item had, which the
# engine downgrades to kinetic text (the proof run then covers that path too).
TYPES = {"short": ["kinetic", "footage", "chart", "flow", "kinetic", "kinetic"],
         "reel": ["kinetic", "chart", "footage", "kinetic", "kinetic", "kinetic"]}
ON_SCREEN = ["Why does saved money shrink?", "Prices up, basket smaller", "Price index (made-up numbers)",
             "Real return = gap", "Check what it buys", "Follow UllasLab"]
REF_TEXT = ("This is a synthetic reference voice for the engine's public test render. It reads a short neutral passage "
            "about weather, trains and libraries, so the clone step has a few seconds of clear speech to work with.")


def chart() -> dict:
    pts = [{"x": f"{2023 + y}-{3 * q:02d}", "y": round(100 + (4 * y) + q, 1)} for y in (0, 1, 2) for q in (1, 2, 3, 4)]
    c = {"type": "line", "title": "Price index (synthetic)", "unit": "index", "decimals": 1,
         "series": [{"name": "Index", "color": "primary", "points": pts}],
         "source": {"name": "UllasLab test fixture (synthetic, not real figures)", "as_of": "2026-11-01"}, "freshness": "INFERRED",
         "claim_id": "c1"}
    c["chart_hash"] = chart_hash(c)
    return c


def scene(i: int, typ: str) -> dict:
    s = {"id": f"s{i + 1:02d}", "role": ROLES[i], "narration": {"text": NARRATION[i], "start_s": None, "end_s": None, "words": None},
         "visual_objective": "Show the idea of this line clearly", "type": typ, "on_screen_text": ON_SCREEN[i], "data_ref": None,
         "palette": "policy", "camera_move": "slow_push" if typ == "footage" else "static",
         "transition": "cut" if i == 0 else "crossfade", "sfx": "none", "rationale": "One idea per shot, cut when the idea changes"}
    if typ == "footage":
        s.update(search_terms=["supermarket shelf price labels", "shopping basket at checkout", "coins on a kitchen table"],
                 illustrative=True)
    if typ == "chart":
        s["data_ref"] = {"kind": "chart", "ref": "c1"}
    if typ == "flow":
        s["data_ref"] = {"kind": "data_point", "ref": "FIXTURE-POINT"}
    return s


def scenes_doc() -> dict:
    return {"schema_version": 1, "item": "2026-11-12-" + SLUG, "outputs": [
        {"output": o, "aspect": "9:16", "hook_type": "question", "scenes": [scene(i, t) for i, t in enumerate(TYPES[o])]}
        for o in ("short", "reel")]}


def manifest() -> dict:
    segs = [{"id": f"s{i + 1:02d}", "text": {"en": t}} for i, t in enumerate(NARRATION)]
    scenes = [{"id": f"sc{i + 1:02d}", "kind": "hook" if i == 0 else "chart" if i == 2 else "text", "segments": [segs[i]["id"]]}
              for i in range(len(segs))]
    scenes[2]["chart"] = "charts/c1.json"
    scenes[-1]["kind"] = "disclaimer"
    return {"version": 1, "slug": SLUG, "orientation": "vertical", "format": 7, "template": "fixture", "hook_style": "H2",
            "source_lang": "en", "languages": ["en"], "voice_ref": None, "synthetic_voice": True, "disclaimer": {"en": DISCLAIMER},
            "segments": segs, "scenes": scenes,
            "studio": {"primary": "short", "outputs": ["short", "reel"], "target_wpm": 150,
                       "files": ["scenes.json", "meta.json", "charts.resolved.json", "sources.md"]}}


def make_clip(dst: Path, seconds: int = 4) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=720x1280:r=30:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)], check=True)


def build(work: Path, *, ref_voice: bool = True, tts_fn=None) -> Path:
    """Write work/bundle (manifest, chart, studio files), work/voice.wav (Kokoro reference) and prepare work/item with
    generated footage and its asset ledger. Returns the item directory."""
    work = Path(work)
    b = work / "bundle"
    c = chart()
    jdump(manifest(), b / "manifest.json")
    jdump(c, b / "charts" / "c1.json")
    st = b / "studio"
    jdump(scenes_doc(), st / "scenes.json")
    jdump({"c1": c}, st / "charts.resolved.json")
    jdump({"title": "Why saved money buys less each year", "description": DISCLAIMER + "\n\nA test render with made-up numbers.",
           "hashtags": ["#personalfinance"], "synthetic_voice": True, "ai_label": True}, st / "meta.json")
    (st / "sources.md").write_text("| claim | chart_hash | tag | source |\n|---|---|---|---|\n"
                                   f"| c1 | {c['chart_hash']} | INFERRED | UllasLab test fixture (synthetic) |\n", encoding="utf-8")
    if ref_voice:
        if tts_fn is None:
            from ..tts import tts as tts_fn
        tts_fn(REF_TEXT, "en", None, engine="kokoro").save(work / "voice.wav")
    item = prepare_item(work)
    entries = []
    for o in scenes_doc()["outputs"]:
        for sc in o["scenes"]:
            if sc["type"] == "footage":
                rel = f"footage/{o['output']}/{sc['id']}.mp4"
                make_clip(item / rel)
                entries.append({"filename": rel, "scene": sc["id"], "output": o["output"], "orientation": "portrait",
                                "provider": "fixture", "source_url": "https://example.invalid/fixture", "creator": "UllasLab fixture",
                                "licence": {"name": "CC0 1.0 (generated test pattern)",
                                            "url": "https://creativecommons.org/publicdomain/zero/1.0/", "attribution": "",
                                            "credit_required": False, "notice": ""},
                                "download_date": "2026-11-12", "illustrative": True, "sha256": sha256_file(item / rel),
                                "width": 720, "height": 1280, "duration": 4.0})
    write_ledger(item, entries, {"item": SLUG, "notes": "WP8 synthetic fixture"})
    return item


NARRATION_ES = [
    "Por que el dinero ahorrado hoy compra un poco menos cada ano?",
    "Cuando los precios suben en toda la economia, cada unidad de moneda alcanza para menos bienes, y el mismo billete compra una cesta mas pequena.",
    "Este grafico inventado muestra un indice de precios que sube de cien a ciento doce en tres anos.",
    "Los ahorros que rinden menos que esa subida pierden poder de compra, mientras que los que la igualan se mantienen.",
    "Los economistas llaman rendimiento real a la diferencia entre ambos, y conviene revisarlo antes de comparar dos opciones.",
    "Asi que cuando una cifra parezca grande, pregunta que compra. Sigue a UllasLab. Solo educacion.",
]
DUB_LANGS = {"es": NARRATION_ES}


def dub_fixture(work: Path, lang: str = "es", total_s: float = 48.0) -> None:
    """Public-safe dub proof (render.yml `dub` job, workflow_dispatch fixture): the fixture bundle with generic translated text,
    the Kokoro reference voice and a synthetic English master timing (even segment windows), so the dub commands (tts,
    captions, qa) run on the real runner without the private repo, R2 or any payload."""
    from ..synth import _scene_windows
    from .. import tts as T
    work = Path(work)
    b = work / "bundle"
    m = manifest()
    m["languages"] = ["en", lang]
    for sg, t in zip(m["segments"], DUB_LANGS[lang]):
        sg["text"][lang] = t
    m.pop("studio", None)
    jdump(m, b / "manifest.json")
    jdump(chart(), b / "charts" / "c1.json")
    T.tts("This is a synthetic reference voice for the engine's public test render. It reads a short neutral passage about weather, "
          "trains and libraries, so the clone step has a few seconds of clear speech to work with.", "en", None, engine="kokoro").save(work / "voice.wav")
    n = len(m["segments"])
    step = (total_s - 4.0) / n
    times = {sg["id"]: (0.5 + i * step, 0.5 + (i + 1) * step - 0.3) for i, sg in enumerate(m["segments"])}
    scenes, _ = _scene_windows({**m, "scenes": m["scenes"]}, times)
    scenes[-1]["end"] = total_s
    jdump({"lang": "en", "mode": "natural", "source": "fixture", "total_s": total_s, "sr": 48000,
           "segments": [{"id": k, "start": round(a, 3), "end": round(e, 3)} for k, (a, e) in times.items()],
           "scenes": scenes, "overruns": []}, work / "timing_en.json")


def payload_free_plan(dub: str | None = None) -> list[str]:
    """`plan --fixture`: English master only, or (fixture=studio-short-dub) also one dub language for the dub job."""
    rows = [{"lang": dub, "extras": "chatterbox,kokoro", "cache": "chatterbox-kokoro"}] if dub else []
    return ["matrix=" + json.dumps({"include": rows}), "has_dubs=" + ("true" if rows else "false")]


__all__ = ["dub_fixture", "build", "manifest", "scenes_doc", "chart", "ITEM", "payload_free_plan"]
