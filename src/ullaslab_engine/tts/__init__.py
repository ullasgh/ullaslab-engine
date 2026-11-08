"""TTS adapters. Public interface: tts(text, lang, ref_wav) -> Wav."""
from .base import Engine, EngineUnavailable, NoVoiceAvailable, tts, get_engine, register_engine

__all__ = ["Engine", "EngineUnavailable", "NoVoiceAvailable", "tts", "get_engine", "register_engine"]
