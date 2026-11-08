"""Kokoro-82M (Apache-2.0) stock voice. CPU friendly. Languages: en, hi, es, pt, ja (not ar/Indic)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..audio import Wav
from .base import EngineUnavailable

# kokoro lang code, default voice
_LANG = {
    "en": ("a", "af_heart"),
    "hi": ("h", "hf_alpha"),
    "es": ("e", "ef_dora"),
    "pt": ("p", "pf_dora"),
    "ja": ("j", "jf_alpha"),
}
SR = 24000


class KokoroEngine:
    name = "kokoro"
    clones_voice = False

    def __init__(self):
        from kokoro import KPipeline  # noqa: F401  (ImportError handled by registry)
        self._KPipeline = KPipeline
        self._pipes: dict[str, object] = {}

    def supports(self, lang: str) -> bool:
        return lang in _LANG

    def synth(self, text: str, lang: str, ref_wav: Path | None) -> Wav:
        code, voice = _LANG[lang]
        if code not in self._pipes:
            self._pipes[code] = self._KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M")
        chunks = []
        try:
            for _, _, audio in self._pipes[code](text, voice=voice, speed=1.0):
                chunks.append(np.asarray(audio, dtype=np.float32))
        except Exception as e:  # model/g2p failures degrade to fallback
            raise EngineUnavailable(f"kokoro failed: {type(e).__name__}") from None
        if not chunks:
            raise EngineUnavailable("kokoro produced no audio")
        return Wav(np.concatenate(chunks), SR)
