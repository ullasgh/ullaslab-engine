"""Premium style (engine side): chart sequences, brand mark plumbing, transition frame mirror, word timings reaching the renderer."""
import json

import pytest

from studio_fixture import make_item
from test_studio import timed_doc
from ullaslab_engine.studio import scenecache as SC
from ullaslab_engine.studio.assemble import AssembleError, apply_chart_views, build_props

KIT = {"kind": "line", "decimals": 2, "meta": {"metric": "m", "unit": "Percent", "period": "x", "source": {"name": "s", "as_of": "2026-11-09"}, "freshness": "RECENT"},
       "series": [{"name": "A", "points": [{"x": f"2026-10-{d:02d}", "y": round(4.0 + 0.03 * d, 2)} for d in range(1, 25)]}]}


def test_chart_views_values_are_read_from_the_series_and_the_whole_series_is_kept():
    out = apply_chart_views("short/s03", KIT, [
        {"window": {"from": "2026-10-01", "to": "2026-10-12"}, "marks": [{"x": "2026-10-09", "label": "High", "at_word": "4.09"}], "point": {"x": "2026-10-12"}},
        {"window": {"from": "2026-10-10", "to": "2026-10-24"}, "highlight": {"from": "2026-10-16", "to": "2026-10-24", "label": "Last week"},
         "point": {"x": "2026-10-24", "label": "Latest", "at_word": "end"}, "at_word": "then"}])
    assert len(out["series"][0]["points"]) == 24                      # the window moves over the full series
    v0, v1 = out["views"]
    assert v0["marks"] == [{"x": "2026-10-09", "value": 4.27, "label": "High", "atWord": "4.09"}]
    assert v0["point"]["value"] == 4.36 and v1["point"]["value"] == 4.72 and v1["atWord"] == "then"
    assert out["meta"]["period"] == "2026-10-01 to 2026-10-24" and out["includeZero"] is False


@pytest.mark.parametrize("views,msg", [
    ([], "1 to 4 views"),
    ([{"window": {"from": "2026-10-05", "to": "2026-10-05"}}], "at least 2"),
    ([{"window": {"from": "2026-10-01", "to": "2026-10-10"}, "marks": [{"x": "2026-10-20"}]}], "observation date inside its window"),
    ([{"window": {"from": "2026-10-01", "to": "2026-10-10"}, "point": {"x": "2026-10-03T00"}}], "observation date"),
    ([{"window": {"from": "2026-10-01", "to": "2026-10-10"}, "highlight": {"from": "2026-10-02", "to": "2026-10-20"}}], "highlight must lie inside"),
    ([{"window": {"from": "2026-10-10", "to": "2026-10-01"}}], "starts after"),
    ([{"window": {"from": "2026-10-01", "to": "2026-10-10"}, "typo": 1}], "unknown key"),
    ([{"window": {"from": "2026-10-01", "to": "2026-10-10"}}] * 5, "1 to 4 views"),
])
def test_bad_chart_views_are_refused_with_the_scene_id(views, msg):
    with pytest.raises(AssembleError, match=msg):
        apply_chart_views("short/s03", KIT, views)


def test_chart_views_need_a_single_series_line_chart():
    with pytest.raises(AssembleError, match="line chart"):
        apply_chart_views("s", {**KIT, "kind": "bar"}, [{"window": {"from": "a", "to": "b"}}])
    two = {**KIT, "series": KIT["series"] * 2}
    with pytest.raises(AssembleError, match="single-series"):
        apply_chart_views("s", two, [{"window": {"from": "2026-10-01", "to": "2026-10-10"}}])


def test_premium_item_style_brand_mark_and_word_timings_reach_props(tmp_path):
    item = make_item(tmp_path, voice=False)
    doc = timed_doc()
    doc["style"] = "premium"
    nar = doc["outputs"][0]["scenes"][0]["narration"]
    nar["words"] = [{"w": "x", "start": nar["start_s"], "end": nar["start_s"] + 0.3}]
    p, _ = build_props(item, doc, doc["outputs"][0], tmp_path / "pub", clip_prep=lambda *a: None)
    assert p["style"] == "premium" and "brandMark" not in p
    assert p["scenes"][0]["narration"]["words"][0]["w"] == "x"       # the renderer matches displayed words to the spoken ones
    mark = {"viewBox": 24, "radius": 6, "bg": "#000000", "ink": "#ffffff", "strokes": [], "rects": []}
    (item / "brand_mark.json").write_text(json.dumps(mark))
    p2, _ = build_props(item, doc, doc["outputs"][0], tmp_path / "pub", clip_prep=lambda *a: None)
    assert p2["brandMark"] == mark and "brandMark" in SC.OPTIONAL_KEYS


def test_premium_transitions_have_frames_and_the_director_names_map_per_style():
    for k in ("push_through", "morph", "sweep", "interrupt"):
        assert SC.TRANSITION_FRAMES[k] > 0
    sc = lambda i, t, **k: {"id": i, "narration": {"start_s": 0.0 if i == "a" else 2.0, "end_s": 2.0 if i == "a" else 4.0}, "transition": t, **k}
    classic = SC.frame_plan([sc("a", "cut"), sc("b", "pattern_interrupt")])
    premium = SC.frame_plan([sc("a", "cut"), sc("b", "pattern_interrupt")], style="premium")
    assert classic[0]["until"] - classic[0]["end"] == 0 and premium[0]["until"] - premium[0]["end"] == SC.TRANSITION_FRAMES["interrupt"]
    own = SC.frame_plan([sc("a", "cut"), sc("b", "push", style="premium")])
    assert own[0]["until"] - own[0]["end"] == SC.TRANSITION_FRAMES["push_through"]


def test_premium_default_sfx_is_capped_never_overrides_and_is_off_for_other_styles():
    from ullaslab_engine.studio import audio as A
    sc = lambda i, t, **k: {"id": f"s{i}", "narration": {"start_s": float(i), "end_s": i + 1.0}, "transition": t, **k}
    scenes = [sc(0, "cut")] + [sc(i, "wipe") for i in range(1, 12)] + [sc(12, "pattern_interrupt")]
    out = A.premium_defaults(scenes, "premium")
    named = [s for s in out if s.get("sfx")]
    assert len(named) == A.PREMIUM_SFX_CAP and out[0].get("sfx") is None
    assert out[12]["sfx"] == "hit"                                   # the interrupt keeps its sound when the cap bites
    assert A.premium_defaults(scenes, "data-story") is scenes and A.premium_defaults(scenes, None) is scenes
    own = [sc(0, "cut"), sc(1, "wipe", sfx="none"), sc(2, "wipe", sfx="tick")]
    assert [s.get("sfx") for s in A.premium_defaults(own, "premium")] == [None, "none", "tick"]   # explicit choices win
    assert all(n in A.SFX for _, n in [(0, s["sfx"]) for s in named])   # only the existing synthesised effects
