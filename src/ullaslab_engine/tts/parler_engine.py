"""Indic Parler-TTS (Apache-2.0) stock voice for hi, ta, te, kn, ml, mr, bn, gu. No cloning.
Voice is chosen by a text description plus a named speaker. Speaker names follow the model card
and are overridable through SPEAKERS; verify against the card when upgrading the model."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..audio import Wav
from .base import EngineUnavailable

MODEL = "ai4bharat/indic-parler-tts"
SPEAKERS = {
    "hi": "Rohit", "ta": "Jaya", "te": "Prakash", "kn": "Suresh",
    "ml": "Anjali", "mr": "Sunita", "bn": "Aditi", "gu": "Neha",
}
_DESC = "{spk}'s voice is calm, clear and steady, at a moderate pace, recorded very close with no background noise."


class IndicParlerEngine:
    name = "indic_parler"
    clones_voice = False

    def __init__(self):
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer
        self._torch = torch
        self._model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL).to("cpu")
        self._tok = AutoTokenizer.from_pretrained(MODEL)
        self._dtok = AutoTokenizer.from_pretrained(self._model.config.text_encoder._name_or_path)

    def supports(self, lang: str) -> bool:
        return lang in SPEAKERS

    def synth(self, text: str, lang: str, ref_wav: Path | None) -> Wav:
        t = self._torch
        try:
            d = self._dtok(_DESC.format(spk=SPEAKERS[lang]), return_tensors="pt")
            p = self._tok(text, return_tensors="pt")
            with t.no_grad():
                out = self._model.generate(
                    input_ids=d.input_ids, attention_mask=d.attention_mask,
                    prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
        except Exception as e:
            raise EngineUnavailable(f"indic_parler failed: {type(e).__name__}") from None
        return Wav(out.cpu().numpy().astype(np.float32).reshape(-1), int(self._model.config.sampling_rate))
