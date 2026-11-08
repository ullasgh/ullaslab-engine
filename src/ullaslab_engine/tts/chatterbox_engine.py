"""Chatterbox-Multilingual (MIT) voice clone. Pin version: upstream retired Aug 2026 (feasibility B3).
Languages of ours it covers: en, hi, es, pt, ar, ja. Output carries Resemble's PerTh watermark (kept)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..audio import Wav
from .base import EngineUnavailable

_LANGS = {"en", "hi", "es", "pt", "ar", "ja"}


class ChatterboxEngine:
    name = "chatterbox"
    clones_voice = True

    def __init__(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # ImportError -> EngineUnavailable
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = ChatterboxMultilingualTTS.from_pretrained(device=dev)

    def supports(self, lang: str) -> bool:
        return lang in _LANGS

    def synth(self, text: str, lang: str, ref_wav: Path | None) -> Wav:
        try:
            wav = self._model.generate(text, language_id=lang, audio_prompt_path=str(ref_wav))
        except Exception as e:
            raise EngineUnavailable(f"chatterbox failed: {type(e).__name__}") from None
        arr = wav.detach().cpu().numpy().astype(np.float32).reshape(-1)
        return Wav(arr, int(self._model.sr))
