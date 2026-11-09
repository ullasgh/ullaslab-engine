"""Config-driven provider registry (config/broll.yaml): enabled flags, order, per-provider rate limits."""
from __future__ import annotations
from pathlib import Path

import yaml

from ..config import ROOT
from .base import Http, load_env
from .providers import (AIProvider, ManualImportProvider, NasaProvider, PexelsProvider, PixabayProvider,
                        WikimediaCommonsProvider)

CLASSES = {"pixabay": PixabayProvider, "nasa": NasaProvider, "wikimedia": WikimediaCommonsProvider,
           "manual": ManualImportProvider, "pexels": PexelsProvider, "ai": AIProvider}
KEYS = {"pixabay": "PIXABAY_API_KEY", "pexels": "PEXELS_API_KEY"}


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or ROOT / "config" / "broll.yaml").read_text(encoding="utf-8"))


def build_providers(cfg: dict, http: Http, env: dict[str, str] | None = None, root: Path = ROOT) -> tuple[list, list[str]]:
    """Return (enabled providers in configured order, notes about skipped ones). Never raises for a missing key:
    key-gated providers are skipped with a note. 'ai' can never be enabled from config."""
    env = env if env is not None else load_env(root)
    out, notes = [], []
    for entry in cfg["providers"]:
        name = entry["name"]
        if name == "ai":
            if entry.get("enabled"):
                notes.append("ai: refused (hard-disabled; needs WP9 research and owner approval)")
            continue
        if not entry.get("enabled", CLASSES[name].default_enabled):
            notes.append(f"{name}: disabled in config")
            continue
        kw = {}
        if name in KEYS:
            key = env.get(KEYS[name], "")
            if not key:
                notes.append(f"{name}: pending-key ({KEYS[name]} not set)")
                continue
            kw["api_key"] = key
        if name == "manual":
            inbox = Path(entry.get("inbox", "footage/inbox"))
            kw["inbox"] = inbox if inbox.is_absolute() else root / inbox
        http.configure(name, min_interval_s=float(entry.get("min_interval_s", 0)), max_requests=entry.get("max_requests"))
        out.append(CLASSES[name](http=http, options=entry, **kw))
    return out, notes
