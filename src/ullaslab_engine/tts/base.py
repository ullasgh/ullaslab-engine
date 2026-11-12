"""Engine interface, registry and the language-aware tts() entry point.

Engine selection comes from config/languages.yaml (tts_engine, fallback_engine).
ULLASLAB_TTS_FORCE=<engine> overrides it (used by the local fixture and tests).
Engines are imported lazily so a CI job installs only the extras it needs.
"""
from __future__ import annotations
import importlib
import logging
import os
from pathlib import Path
from typing import Callable, Protocol

from ..audio import Wav, normalize_loudness
from ..config import language

log = logging.getLogger("ullaslab.tts")


class EngineUnavailable(RuntimeError):
    """Engine package or weights missing, or engine failed to produce audio. `error_class` names the underlying
    exception class (never its text: that can quote paths or script)."""

    def __init__(self, msg: str = "", error_class: str | None = None):
        super().__init__(msg)
        self.error_class = error_class


class NoVoiceAvailable(RuntimeError):
    """No engine (primary or fallback) can voice this language. `failures` is [(engine, exception class)]: the dub
    stage records it and fails the TTS step instead of silently shipping captions only."""

    def __init__(self, msg: str = "", failures: list[tuple[str, str]] | None = None):
        super().__init__(msg)
        self.failures = list(failures or [])


class Engine(Protocol):
    name: str
    clones_voice: bool

    def supports(self, lang: str) -> bool: ...
    def synth(self, text: str, lang: str, ref_wav: Path | None) -> Wav: ...
    # Engines that set uses_settings = True also accept settings=<dict> (see voice/settings.py).


_FACTORIES: dict[str, Callable[[], Engine]] = {}
_CACHE: dict[str, Engine] = {}

_BUILTIN = {
    "kokoro": "ullaslab_engine.tts.kokoro_engine:KokoroEngine",
    "chatterbox": "ullaslab_engine.tts.chatterbox_engine:ChatterboxEngine",
    "indic_parler": "ullaslab_engine.tts.parler_engine:IndicParlerEngine",
}


def register_engine(name: str, factory: Callable[[], Engine]) -> None:
    _FACTORIES[name] = factory
    _CACHE.pop(name, None)


def get_engine(name: str) -> Engine:
    if name in _CACHE:
        return _CACHE[name]
    if name in _FACTORIES:
        try:
            eng = _FACTORIES[name]()
        except EngineUnavailable:
            raise
        except Exception as e:
            raise EngineUnavailable(f"{name}: failed to load ({type(e).__name__})", type(e).__name__) from None
    elif name in _BUILTIN:
        mod, cls = _BUILTIN[name].split(":")
        try:
            eng = getattr(importlib.import_module(mod), cls)()
        except ImportError as e:
            raise EngineUnavailable(f"{name}: extra not installed ({e.name})", "ImportError") from None
        except Exception as e:  # weights missing offline, bad install, out of memory: a load failure of THIS engine
            raise EngineUnavailable(f"{name}: failed to load ({type(e).__name__})", type(e).__name__) from None
    else:
        raise EngineUnavailable(f"unknown engine {name}")
    _CACHE[name] = eng
    return eng


def plan_engines(lang: str) -> list[str]:
    """Ordered engine names to try for a language."""
    forced = os.environ.get("ULLASLAB_TTS_FORCE")
    if forced:
        return [forced]
    cfg = language(lang)
    order = [cfg["tts_engine"], cfg.get("fallback_engine", "none")]
    return [e for e in order if e and e != "none"]


def tts(text: str, lang: str, ref_wav: Path | str | None = None, *, normalize: bool = True, engine: str | None = None,
        settings: dict | None = None) -> Wav:
    """Synthesise text in lang. Clone engines use ref_wav; stock engines ignore it.

    Tries the primary engine then the fallback; raises NoVoiceAvailable when none works.
    The returned audio is loudness-normalised to -14 LUFS unless normalize=False
    (the pipeline normalises the assembled track instead, to keep relative levels).
    """
    ref = Path(ref_wav) if ref_wav else None
    errors, failures = [], []
    for name in ([engine] if engine else plan_engines(lang)):
        try:
            eng = get_engine(name)
            if not eng.supports(lang):
                raise EngineUnavailable(f"{name} does not support {lang}")
            if eng.clones_voice and ref is None:
                raise EngineUnavailable(f"{name} needs a reference wav")
            w = eng.synth(text, lang, ref, settings=settings) if getattr(eng, "uses_settings", False) and settings else eng.synth(text, lang, ref)
            if w is None or len(w.samples) == 0:
                raise EngineUnavailable(f"{name} returned empty audio")
            w.engine = name
            return normalize_loudness(w) if normalize else w
        except EngineUnavailable as e:
            log.warning("tts engine %s unusable for %s: %s", name, lang, e)
            errors.append(f"{name}: {e}")
            failures.append((name, getattr(e, "error_class", None) or type(e).__name__))
    raise NoVoiceAvailable(f"{lang}: " + "; ".join(errors) if errors else lang, failures)


def engine_used(lang: str) -> str | None:
    """First engine in the plan that loads and supports the language (no synthesis)."""
    for name in plan_engines(lang):
        try:
            if get_engine(name).supports(lang):
                return name
        except EngineUnavailable:
            continue
    return None
