"""Slow: real Remotion + headless Chrome. Run with RUN_RENDER=1 (make test-render). Audits every
format template, both orientations, and the RTL/Indic/CJK languages against QA gate A5."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import fake_tts_factory
from ullaslab_engine import pipeline as P
from ullaslab_engine.config import ROOT
from ullaslab_engine.qa import gate_a5

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_RENDER"), reason="set RUN_RENDER=1 (needs node + Chrome)")


def audit(work: Path, lang: str, orientation: str, natural: bool, fmt: int, tag: str) -> dict:
    props = P.make_props(work, lang, orientation, natural)
    props["format"] = fmt
    d = work / f"smoke_{tag}"
    (d / "public").mkdir(parents=True)
    shutil.copy(work / lang / ("audio_natural.wav" if natural else "audio.wav"), d / "public" / "audio.wav")
    P.jdump(props, d / "props.json")
    subprocess.run(["node", str(ROOT / "remotion" / "render.mjs"), "--props", str(d / "props.json"), "--public", str(d / "public"),
                    "--audit", str(d / "layout.json"), "--no-video"], check=True, cwd=ROOT / "remotion", timeout=900)
    layout = P.jload(d / "layout.json")
    cues = P.jload(work / lang / ("cues_natural.json" if natural else "cues.json"))
    return gate_a5(layout, cues, orientation)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    work = tmp_path_factory.mktemp("w")
    shutil.copytree(ROOT / "fixtures" / "fixture-bundle", work / "bundle")
    m = json.loads((work / "bundle" / "manifest.json").read_text())
    # exercise the myth and Q&A scene kinds too
    for sc in m["scenes"]:
        if sc["id"] == "s6":
            sc["kind"] = "myth"
        if sc["id"] == "s5":
            sc.update(kind="qa", headline={"en": "Is this lagged?", "hi": "क्या यह देर से है?", "ar": "هل هي متأخرة؟", "ja": "遅れていますか"},
                      body={"en": "Yes, by 60 days.", "hi": "हाँ, 60 दिन।", "ar": "نعم، 60 يوما.", "ja": "はい、60日です。"})
            sc.pop("items", None)
    (work / "bundle" / "manifest.json").write_text(json.dumps(m, ensure_ascii=False))
    f = fake_tts_factory(2.6)
    P.stage_tts(work, "en", tts_fn=f)
    P.stage_captions(work, "en", use_asr=False)
    for l in ("hi", "ar", "ja"):
        P.stage_tts(work, l, tts_fn=fake_tts_factory(2.6 if l != "ja" else 0.25), want_natural=True)
        P.stage_captions(work, l, use_asr=False)
    return work


def checks_failed(g):
    return [(c["name"], c["value"]) for c in g["checks"] if not c["passed"]]


@pytest.mark.parametrize("fmt", range(1, 11))
def test_each_template_passes_a5_vertical(prepared, fmt):
    g = audit(prepared, "en", "vertical", False, fmt, f"v{fmt}")
    assert g["passed"], checks_failed(g)


def test_horizontal_passes_a5(prepared):
    g = audit(prepared, "en", "horizontal", False, 1, "h1")
    assert g["passed"], checks_failed(g)


@pytest.mark.parametrize("lang", ["hi", "ar", "ja"])
def test_dubbed_visual_variants_pass_a5(prepared, lang):
    g = audit(prepared, lang, "vertical", True, 4, f"l{lang}")
    assert g["passed"], checks_failed(g)
