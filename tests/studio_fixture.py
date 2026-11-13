"""Builds the small studio fixture item: 4 scenes x 3 outputs (long 16:9, short and reel 9:16), a ~20 s synthetic voice
(macOS `say`), generated footage clips with an asset ledger, and a resolved chart. No network, no paid anything."""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path

from ullaslab_engine.broll.ledger import sha256_file, write_ledger

NARRATION = [
    "Why did a bond auction in Tokyo move rates in Texas?",
    "Japanese investors hold a large share of United States government debt, so a weak auction there can lift yields here.",
    "Look at the ten year yield over the last three years, it rose from two point five percent to four percent.",
    "When borrowing costs rise, mortgages, car loans and company debt can all become more expensive. Follow UllasLab.",
]
ROLES = ["hook", "setup", "evidence", "consequence"]
TYPES = {"long": ["kinetic", "footage", "chart", "map"], "short": ["kinetic", "chart", "footage", "map"], "reel": ["kinetic", "footage", "chart", "kinetic"]}
SFX = ["none", "whoosh", "tick", "riser"]
TRANS = ["cut", "crossfade", "wipe", "match_cut"]


def scene(i: int, typ: str, text: str) -> dict:
    s = {"id": f"s{i + 1:02d}", "role": ROLES[i], "narration": {"text": text, "start_s": None, "end_s": None, "words": None},
         "visual_objective": "Show the idea described by the narration clearly", "type": typ,
         "on_screen_text": ["Tokyo to Texas?", "Who owns US debt", "The 10-year yield|rose *sharply*", "Borrowing costs ripple"][i] if typ != "map" else "Where the money flows",
         "data_ref": None, "palette": "policy", "camera_move": "slow_push", "transition": TRANS[i], "sfx": SFX[i],
         "rationale": "Matches the narration beat and keeps one idea per shot"}
    if typ == "footage":
        s.update(search_terms=["container ship harbour", "stock exchange trading floor", "city skyline night"], illustrative=True)
    if typ == "chart":
        s["data_ref"] = {"kind": "chart", "ref": "c1"}
    return s


def scenes_doc(item: str = "2026-11-10-tokyo-texas") -> dict:
    outs = [{"output": o, "aspect": "16:9" if o == "long" else "9:16", "hook_type": "mystery",
             "scenes": [scene(i, t, NARRATION[i]) for i, t in enumerate(TYPES[o])]} for o in ("long", "short", "reel")]
    return {"schema_version": 1, "item": item, "outputs": outs}


def chart() -> dict:
    pts = [{"x": f"2023-{m:02d}", "y": round(2.5 + m * 0.125, 2)} for m in range(1, 13)]
    return {"c1": {"type": "line", "title": "US 10-year Treasury yield", "unit": "% per year", "decimals": 2,
                   "series": [{"name": "10-year", "color": "primary", "points": pts}],
                   "source": {"name": "UllasLab fixture (synthetic, not real figures)", "as_of": "2026-11"}, "freshness": "INFERRED", "claim_id": "c1"}}


def say_voice(dst: Path, text: str, rate: int = 170) -> None:
    aiff = dst.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Samantha", "-r", str(rate), "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "24000", "-ac", "1", str(dst)], check=True)
    aiff.unlink()


def make_clip(dst: Path, seconds: int = 3) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=25:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)], check=True)


def make_item(root: Path, voice: bool = True) -> Path:
    item = root / "2026-11-10-tokyo-texas"
    item.mkdir(parents=True)
    doc = scenes_doc(item.name)
    (item / "scenes.json").write_text(json.dumps(doc, indent=1))
    (item / "chart_specs.json").write_text(json.dumps(chart()))
    (item / "meta.json").write_text(json.dumps({"title": "Why a bond auction in Tokyo can move US rates", "hashtags": ["#bonds"]}))
    if voice:
        say_voice(item / "voice.wav", " ".join(NARRATION))
    entries = []
    for o in doc["outputs"]:
        for sc in o["scenes"]:
            if sc["type"] == "footage":
                rel = f"footage/{o['output']}/{sc['id']}.mp4"
                make_clip(item / rel)
                entries.append({"filename": rel, "scene": sc["id"], "output": o["output"], "orientation": "x", "provider": "fixture",
                                "source_url": "https://example.invalid/fixture", "creator": "UllasLab fixture",
                                "licence": {"name": "CC0 1.0 (generated test pattern)", "url": "https://creativecommons.org/publicdomain/zero/1.0/",
                                            "attribution": "", "credit_required": False, "notice": ""},
                                "download_date": "2026-11-09", "illustrative": True, "sha256": sha256_file(item / rel), "width": 640, "height": 360,
                                "duration": float(3)})
    write_ledger(item, entries, {"item": item.name, "notes": "fixture"})
    return item
