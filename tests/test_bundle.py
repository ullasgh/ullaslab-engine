import json
import pytest
from ullaslab_engine.bundle import BundleError, load_bundle, normalise_for_wer, validate_chart


def test_fixture_bundle_loads_with_charts(bundle_dir):
    m = load_bundle(bundle_dir)
    assert len(m["scenes"]) == 7 and m["scenes"][0]["chart_data"]["type"] == "line"


def test_chart_schema_rejects_bad_charts():
    ok = {"type": "counter", "title": "t", "value": 1.0, "source": {"name": "x", "as_of": "2026-01-01"}, "freshness": "LIVE"}
    validate_chart(ok)
    for bad in [dict(ok, freshness="FRESH"), dict(ok, source={"name": "x", "as_of": "yesterday"}),
                {k: v for k, v in ok.items() if k != "source"}, dict(ok, type="line"), dict(ok, extra=1),
                dict(ok, type="delta")]:
        with pytest.raises(BundleError):
            validate_chart(bad)


def test_manifest_errors(bundle_dir):
    p = bundle_dir / "manifest.json"
    m = json.loads(p.read_text())
    m["scenes"][0]["segments"] = ["nope"]
    p.write_text(json.dumps(m))
    with pytest.raises(BundleError):
        load_bundle(bundle_dir)


def test_chart_path_cannot_escape(bundle_dir):
    p = bundle_dir / "manifest.json"
    m = json.loads(p.read_text())
    m["scenes"][0]["chart"] = "../../etc/passwd"
    p.write_text(json.dumps(m))
    with pytest.raises(BundleError):
        load_bundle(bundle_dir)


def test_wer_normaliser():
    assert normalise_for_wer("Up 4.5%, and 1,234!") == normalise_for_wer("up 4.5 percent and 1234")


def test_schema_errors_never_echo_values(bundle_dir):
    import json
    p = bundle_dir / "manifest.json"
    m = json.loads(p.read_text())
    m["slug"] = "SECRET SCRIPT TEXT"
    p.write_text(json.dumps(m))
    with pytest.raises(BundleError) as e:
        load_bundle(bundle_dir)
    assert "SECRET" not in str(e.value)
