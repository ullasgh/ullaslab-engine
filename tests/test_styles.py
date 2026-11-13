"""V2 M2 video styles: props plumbing, the still checker (synthetic stills, no render) and, with RUN_RENDER=1, the real
Remotion stills for every style in both aspect ratios. Rendered media goes to a temp folder and is never committed."""
import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from studio_fixture import make_item
from test_studio import timed_doc
from ullaslab_engine.config import ROOT
from ullaslab_engine.studio.assemble import STYLES, build_props
from ullaslab_engine.studio.style_check import blank, check_dir, check_still


def props(tmp_path, doc, i=0):
    item = make_item(tmp_path, voice=False)
    return build_props(item, doc, doc["outputs"][i], tmp_path / "pub", clip_prep=lambda *a: None)


def test_styles_match_remotion_and_content_schema_names():
    ts = (ROOT / "remotion" / "src" / "studio" / "styles.ts").read_text()
    ids = re.search(r"STYLE_IDS = \[([^\]]*)\]", ts).group(1)
    assert tuple(re.findall(r'"([a-z-]+)"', ids)) == STYLES == ("data-story", "creator-motion", "chalk-talk", "clean-tech", "premium")


def test_no_style_means_no_style_prop(tmp_path):
    p, warns = props(tmp_path, timed_doc())
    assert "style" not in p and not [w for w in warns if "style" in w]
    assert all("style" not in s for s in p["scenes"])


@pytest.mark.parametrize("style", STYLES)
def test_item_style_reaches_props_for_every_output(tmp_path, style):
    doc = timed_doc()
    doc["style"] = style
    for i in range(3):
        p, _ = props(tmp_path / str(i), doc, i)
        assert p["style"] == style


def test_scene_style_rides_in_scenes_and_unknown_is_dropped(tmp_path):
    doc = timed_doc()
    doc["style"] = "data-story"
    doc["outputs"][0]["scenes"][0]["style"] = "creator-motion"
    doc["outputs"][0]["scenes"][2]["style"] = "hologram"
    p, warns = props(tmp_path, doc)
    assert p["scenes"][0]["style"] == "creator-motion" and p["style"] == "data-story"
    assert "style" not in p["scenes"][2] and any("unknown style 'hologram'" in w for w in warns)
    assert doc["outputs"][0]["scenes"][2]["style"] == "hologram"          # the input document is not mutated


def test_unknown_item_style_is_ignored(tmp_path):
    doc = timed_doc()
    doc["style"] = "hologram"
    assert "style" not in props(tmp_path, doc)[0]


def test_style_does_not_change_chart_data_or_endcard(tmp_path):
    base, _ = props(tmp_path / "a", timed_doc())
    doc = timed_doc()
    doc["style"] = "data-story"
    styled, _ = props(tmp_path / "b", doc)
    for k in ("refs", "captions", "endCard", "durationInFrames"):
        assert styled[k] == base[k], k


# ------------------------------------------------------------------ still checker on synthetic stills
def rec(**kw):
    base = {"style": "data-story", "aspect": "16:9", "frame": 75, "file": "a.png", "width": 1920, "height": 1080, "fonts": [{"family": "Noto Sans", "weight": 700, "loaded": True}], "elements": [
        {"role": "headline", "x": 100, "y": 60, "w": 800, "h": 90, "fontPx": 80},
        {"role": "stamp", "x": 100, "y": 780, "w": 900, "h": 44, "fontPx": 36},
        {"role": "caption", "x": 500, "y": 960, "w": 900, "h": 70, "fontPx": 50}]}
    base.update(kw)
    return base


def png(path, size=(1920, 1080), noisy=True):
    im = Image.new("RGB", size, (11, 20, 36))
    if noisy:
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        for x in range(100, min(900, size[0] - 60), 40):
            d.rectangle([x, 60, x + 20, min(size[1] - 1, 260)], fill=(255, 255, 255))
    im.save(path)
    return path


def test_checker_passes_good_still_and_flags_each_failure(tmp_path):
    f = png(tmp_path / "a.png")
    assert check_still(rec(), f) == []
    assert any("expected 1920x1080" in b for b in check_still(rec(width=1280), f))
    assert any("png is" in b for b in check_still(rec(), png(tmp_path / "s.png", (800, 450))))
    assert any("blank" in b for b in check_still(rec(), png(tmp_path / "b.png", noisy=False)))
    r = rec(); r["elements"][0]["x"] = 1700                                   # headline past the right safe edge
    assert any("outside the content box" in b for b in check_still(r, f))
    r = rec(); r["elements"][1]["y"] = 1000                                   # stamp inside the caption reserve
    assert any("stamp text outside" in b or "overlaps the caption" in b for b in check_still(r, f))
    r = rec(); r["elements"][0]["fontPx"] = 30
    assert any("below" in b for b in check_still(r, f))
    r = rec(); r["elements"][2]["x"] = 5
    assert any("caption leaves the safe box" in b for b in check_still(r, f))
    assert any("not loaded" in b for b in check_still(rec(fonts=[{"family": "Noto Sans", "weight": 700, "loaded": False}]), f))
    assert any("no rendered-font data" in b for b in check_still(rec(fonts=[]), f))
    assert any("still missing" in b for b in check_still(rec(), tmp_path / "none.png"))
    assert any("no headline" in b for b in check_still(rec(elements=[]), f))


def test_checker_vertical_zones(tmp_path):
    f = png(tmp_path / "v.png", (1080, 1920))
    r = rec(aspect="9:16", width=1080, height=1920)
    r["elements"] = [{"role": "headline", "x": 70, "y": 300, "w": 700, "h": 90, "fontPx": 68},
                     {"role": "caption", "x": 100, "y": 1400, "w": 780, "h": 70, "fontPx": 44}]
    assert check_still(r, f) == []
    r["elements"][0]["y"] = 100                                               # inside the platform UI band at the top
    assert any("outside the content box" in b for b in check_still(r, f))


def test_blank_detector(tmp_path):
    assert blank(png(tmp_path / "x.png", noisy=False))
    assert blank(png(tmp_path / "y.png")) is None


# ------------------------------------------------------------------ real render (slow)
@pytest.mark.skipif(not os.environ.get("RUN_RENDER"), reason="set RUN_RENDER=1 (needs node + Chrome)")
def test_style_stills_render_and_pass_checks(tmp_path_factory):
    out = Path(os.environ.get("STYLE_STILLS_OUT") or tmp_path_factory.mktemp("style-stills"))
    subprocess.run(["node", "scripts/style-stills.mjs", str(out)], check=True, cwd=ROOT / "remotion", timeout=900)
    recs = json.loads((out / "audit.json").read_text())
    assert len(recs) == 4 * 2 * 3
    assert {(r["style"], r["aspect"]) for r in recs} == {(s, a) for s in STYLES for a in ("16:9", "9:16")}
    assert check_dir(out) == []


def test_manifest_schema_accepts_style_enum_only():
    import jsonschema
    schema = json.loads((ROOT / "schema" / "manifest.schema.json").read_text())
    assert schema["properties"]["style"]["enum"] == list(STYLES)
    fixture = json.loads((ROOT / "fixtures" / "fixture-bundle" / "manifest.json").read_text())
    jsonschema.validate(fixture, schema)
    jsonschema.validate({**fixture, "style": "clean-tech"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**fixture, "style": "hologram"}, schema)


def test_styled_chart_without_source_name_fails_in_build_props(tmp_path):
    doc = timed_doc()
    doc["style"] = "data-story"
    item = make_item(tmp_path, voice=False)
    import json as _j
    ref = next(sc["data_ref"]["ref"] for sc in doc["outputs"][0]["scenes"] if sc["type"] == "chart")
    from ullaslab_engine.studio import assemble as A
    orig = A.to_kit_chart
    A.to_kit_chart = lambda r, c: (lambda k: (k["meta"]["source"].update(name=""), k)[1])(orig(r, c))
    try:
        from ullaslab_engine.studio.assemble import AssembleError
        with pytest.raises(AssembleError, match="needs a source name"):
            build_props(item, doc, doc["outputs"][0], tmp_path / "pub", clip_prep=lambda *a: None)
    finally:
        A.to_kit_chart = orig
