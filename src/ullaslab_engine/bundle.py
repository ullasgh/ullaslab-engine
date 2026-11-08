"""Bundle (manifest + charts) loading and validation. A bundle is a directory (zip extracted)."""
from __future__ import annotations
import json
import re
from pathlib import Path
import jsonschema

from .config import ROOT

SCHEMA_DIR = ROOT / "schema"
_TAG = re.compile(r"[^\w\s]", re.UNICODE)


class BundleError(ValueError):
    pass


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate_chart(chart: dict) -> None:
    try:
        jsonschema.validate(chart, _schema("chart.schema.json"))
    except jsonschema.ValidationError as e:
        raise BundleError(f"chart invalid at {list(e.absolute_path)}: {e.message[:120]}") from None


def load_bundle(root: Path) -> dict:
    """Load manifest.json, validate it and inline the chart JSON. Returns the manifest dict."""
    root = Path(root)
    try:
        m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        jsonschema.validate(m, _schema("manifest.schema.json"))
    except FileNotFoundError:
        raise BundleError("manifest.json missing") from None
    except jsonschema.ValidationError as e:
        raise BundleError(f"manifest invalid at {list(e.absolute_path)}: {e.message[:120]}") from None
    seg_ids = {s["id"] for s in m["segments"]}
    if len(seg_ids) != len(m["segments"]):
        raise BundleError("duplicate segment ids")
    src = m.get("source_lang", "en")
    for s in m["segments"]:
        if src not in s["text"]:
            raise BundleError(f"segment {s['id']} lacks source language text")
    for sc in m["scenes"]:
        for sid in sc.get("segments", []):
            if sid not in seg_ids:
                raise BundleError(f"scene {sc['id']} references unknown segment {sid}")
        if "chart" in sc:
            p = (root / sc["chart"]).resolve()
            if root.resolve() not in p.parents:
                raise BundleError("chart path escapes bundle")
            chart = json.loads(p.read_text(encoding="utf-8"))
            validate_chart(chart)
            sc["chart_data"] = chart
        elif sc["kind"] in ("chart", "counter", "compare"):
            raise BundleError(f"scene {sc['id']} of kind {sc['kind']} needs a chart")
    m.setdefault("source_lang", "en")
    return m


def seg_text(m: dict, seg: dict, lang: str) -> str:
    """Text of a segment in lang, falling back to the source language."""
    return seg["text"].get(lang) or seg["text"][m["source_lang"]]


def words(text: str) -> list[str]:
    """Whitespace tokens for space-delimited scripts; characters for Japanese-like text."""
    t = text.strip()
    if not t:
        return []
    return t.split()


def normalise_for_wer(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKC", text).casefold().replace("%", " percent ")
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)  # 1,234 -> 1234
    return " ".join(_TAG.sub(" ", t).split())
