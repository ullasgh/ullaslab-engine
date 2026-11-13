"""Watchability slice 1 (engine side): chart views (zoomed window, highlight, annotated point, marks), the settled marker value,
and the fail-fast on flow/timeline scenes without data. Synthetic data only (public repo)."""
import json

import pytest

from ullaslab_engine.studio.assemble import (AssembleError, apply_chart_view, build_props, check_visuals, infer_decimals, to_kit_chart,
                                              validate_visual)


def daily_chart(decimals=None):
    pts = [{"x": f"2026-10-{d:02d}", "y": round(4.0 + 0.01 * d, 2)} for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16)]
    c = {"type": "line", "title": "Synthetic yield, daily", "unit": "percent", "series": [{"name": "Y", "points": pts}],
         "source": {"name": "UllasLab test fixture (synthetic)", "as_of": "2026-10-16"}, "freshness": "INFERRED"}
    if decimals is not None:
        c["decimals"] = decimals
    return c


def kit():
    return to_kit_chart("c1", daily_chart())


def test_decimals_are_inferred_from_the_values_so_a_value_is_never_rounded_on_screen():
    assert infer_decimals([4.88, 4.9]) == 2 and infer_decimals([5, 6]) == 1 and infer_decimals([1.23456]) == 3
    assert kit()["decimals"] == 2 and to_kit_chart("c1", daily_chart(decimals=1))["decimals"] == 1


def test_every_line_chart_settles_its_value_label_at_the_end():
    assert kit()["settle"] is True


def test_window_cuts_the_series_and_unzooms_the_zero_baseline():
    v = apply_chart_view("s03", kit(), {"window": {"from": "2026-10-05", "to": "2026-10-09"}})
    pts = v["series"][0]["points"]
    assert [p["x"] for p in pts] == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    assert v["includeZero"] is False and v["settle"] is True
    assert v["meta"]["period"] == "2026-10-05 to 2026-10-09"
    assert v["marker"] == {"x": "2026-10-09", "y": 4.09}


def test_point_stops_the_line_and_the_marker_is_the_data_value_not_a_typed_one():
    v = apply_chart_view("s05", kit(), {"point": {"x": "2026-10-07", "label": "Dip"}})
    assert v["series"][0]["points"][-1] == {"x": "2026-10-07", "y": 4.07}
    assert v["marker"]["y"] == 4.07
    assert v["annotations"] == [{"x": "2026-10-07", "label": "Dip 4.07"}]


def test_marks_carry_values_read_from_the_series_and_highlight_rides_along():
    v = apply_chart_view("s03", kit(), {"window": {"from": "2026-10-01", "to": "2026-10-12"},
                                         "highlight": {"from": "2026-10-05", "to": "2026-10-08", "label": "Dip"},
                                         "marks": [{"x": "2026-10-02"}], "point": {"x": "2026-10-12"}})
    assert [a["label"] for a in v["annotations"]] == ["4.02", "4.12"]
    assert v["highlight"] == {"from": "2026-10-05", "to": "2026-10-08", "label": "Dip"}


@pytest.mark.parametrize("view,msg", [
    ({"point": {"x": "2026-10-03"}}, "not an observation date"),               # a weekend: no value to show
    ({"window": {"from": "2026-10-14", "to": "2026-10-14"}}, "at least 2"),
    ({"window": {"from": "2026-10-09", "to": "2026-10-05"}}, "starts after it ends"),
    ({"marks": [{"x": "2026-10-01"}] * 4}, "at most 3"),
    ({"highlight": {"from": "2026-09-01", "to": "2026-10-05"}}, "highlight must lie inside"),
    ({"window": {"to": "2026-10-09"}, "marks": [{"x": "2026-10-12"}]}, "not an observation date"),
    ({"bogus": 1}, "unknown key"),
])
def test_bad_views_fail_with_a_public_safe_message(view, msg):
    with pytest.raises(AssembleError, match=msg) as e:
        apply_chart_view("s03", kit(), view)
    assert "2026" not in str(e.value) or "window" in msg   # messages name the rule and the scene, not data


def test_a_view_needs_a_single_series_line_chart():
    bar = to_kit_chart("b", {"type": "bar", "title": "T", "unit": "", "series": [{"name": "s", "points": [{"x": "a", "y": 1}]}],
                             "source": {"name": "x", "as_of": "2026"}, "freshness": "INFERRED"})
    with pytest.raises(AssembleError, match="needs a line chart"):
        apply_chart_view("s03", bar, {"window": {"from": "a"}})
    two = kit()
    two["series"] = two["series"] * 2
    with pytest.raises(AssembleError, match="single-series"):
        apply_chart_view("s03", two, {"window": {"from": "2026-10-01"}})


def test_two_scenes_of_one_chart_get_their_own_views_in_props(tmp_path):
    from studio_fixture import make_item
    from test_studio import timed_doc
    item = make_item(tmp_path, voice=False)
    (item / "chart_specs.json").write_text(json.dumps({"c1": daily_chart()}))
    doc = timed_doc()
    out = doc["outputs"][0]
    charts = [s for s in out["scenes"] if s["type"] == "chart"]
    assert charts, "fixture has a chart scene"
    charts[0]["chart_view"] = {"window": {"from": "2026-10-05", "to": "2026-10-09"}}
    charts[0]["data_ref"] = {"kind": "chart", "ref": "c1"}
    extra = json.loads(json.dumps(charts[0]))
    extra["id"], extra["chart_view"] = "s98", {"point": {"x": "2026-10-07"}}
    out["scenes"].insert(out["scenes"].index(charts[0]) + 1, extra)
    # footage placeholders keep the fixture's other scenes buildable
    props, _ = build_props(item, doc, out, tmp_path / "pub", allow_placeholder=True, clip_prep=lambda *a: None)
    refs = {k: v for k, v in props["refs"].items() if k.startswith("c1@")}
    assert len(refs) == 2
    assert {r["marker"]["y"] for r in refs.values()} == {4.09, 4.07}
    assert all(r["revealFrames"] >= 24 for r in refs.values())
    ids = {s["id"]: s["data_ref"]["ref"] for s in props["scenes"] if s["type"] == "chart"}
    assert ids[charts[0]["id"]] != ids["s98"]


def test_validate_visual_checks_the_shape_the_renderer_needs():
    ok = {"nodes": [{"id": "a", "label": "A", "level": 0}, {"id": "b", "label": "B", "level": 1}], "edges": [{"from": "a", "to": "b"}]}
    validate_visual("short/s04", "flow", ok)
    for bad, msg in [({**ok, "edges": []}, "at least 2 nodes and 1 edge"),
                     ({**ok, "edges": [{"from": "a", "to": "zzz"}]}, "join two node ids"),
                     ({"nodes": [{"id": "a", "label": "A", "level": 0}, {"id": "b", "label": "B", "level": 2}], "edges": ok["edges"]}, "without gaps"),
                     ({"nodes": [{"id": "a", "label": "", "level": 0}, {"id": "b", "label": "B", "level": 1}], "edges": ok["edges"]}, "label")]:
        with pytest.raises(AssembleError, match=msg):
            validate_visual("short/s04", "flow", bad)
    with pytest.raises(AssembleError, match="at least 2 events"):
        validate_visual("short/s04", "timeline", {"events": [{"when": "a", "title": "b"}]})


def test_check_visuals_lists_every_diagram_scene_without_data_before_any_stage_runs(tmp_path):
    item = tmp_path / "i"
    item.mkdir()
    sc = lambda i, t, ref=None: {"id": f"s{i:02d}", "type": t, "data_ref": {"kind": "data_point", "ref": ref} if ref else None}  # noqa: E731
    doc = {"outputs": [{"output": "short", "scenes": [sc(1, "kinetic"), sc(2, "flow", "X"), sc(3, "timeline")]}]}
    bad = check_visuals(item, doc)
    assert len(bad) == 2 and "short/s02" in bad[0] and "short/s03" in bad[1]
    (item / "visual_data.json").write_text(json.dumps({
        "short/s02": {"nodes": [{"id": "a", "label": "A", "level": 0}, {"id": "b", "label": "B", "level": 1}], "edges": [{"from": "a", "to": "b"}]},
        "s03": {"events": [{"when": "Then", "title": "One"}, {"when": "Later", "title": "Two"}]}}))
    assert check_visuals(item, doc) == []


def test_studio_run_stops_at_the_visual_check_before_timings_and_logs_scene_ids_only(tmp_path):
    from ullaslab_engine.studio.run import Studio
    from studio_fixture import make_item
    item = make_item(tmp_path, voice=False)
    d = json.loads((item / "scenes.json").read_text())
    sc = d["outputs"][0]["scenes"][3]
    sc["type"], sc["data_ref"] = "flow", {"kind": "data_point", "ref": "SECRET-LOOKING-REF"}
    (item / "scenes.json").write_text(json.dumps(d))
    logs = []
    called = []
    s = Studio(item, preview=True, asr=lambda p, l: called.append(1), render=lambda *a, **k: called.append(2), log=logs.append)
    with pytest.raises(AssembleError, match="need visual data"):
        s.run()
    assert not called
    text = "\n".join(logs)
    assert "[visual-check] FAIL long/" in text and "text card" in text
    assert "SECRET-LOOKING-REF" not in text
