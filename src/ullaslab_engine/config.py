"""Load the vendored language and quality config (non-secret thresholds)."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def languages() -> dict[str, dict]:
    return {l["code"]: l for l in _load("languages.yaml")["languages"]}


def language(code: str) -> dict:
    try:
        return languages()[code]
    except KeyError:
        raise ValueError(f"unknown language: {code}") from None


def quality() -> dict:
    return _load("quality.yaml")
