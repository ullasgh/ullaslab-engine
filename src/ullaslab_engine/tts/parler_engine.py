"""Indic Parler-TTS (Apache-2.0) stock voice for hi, ta, te, kn, ml, mr, bn, gu. No cloning.
Voice is chosen by a text description plus a named speaker. Speaker names follow the model card
and are overridable through SPEAKERS; verify against the card when upgrading the model."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..audio import Wav
from .base import EngineUnavailable

MODEL = "ai4bharat/indic-parler-tts"
# Recommended speakers from the model card (checked 2026-11-08); index 0 is the default, 1 the alternative.
RECOMMENDED = {
    "hi": ["Rohit", "Divya"], "ta": ["Jaya", "Kavitha"], "te": ["Prakash", "Lalitha"], "kn": ["Suresh", "Anu"],
    "ml": ["Anjali", "Harish"], "mr": ["Sanjay", "Sunita"], "bn": ["Arjun", "Aditi"], "gu": ["Yash", "Neha"],
}
SPEAKERS = {k: v[0] for k, v in RECOMMENDED.items()}
# Calm, close-mic narration. "very clear audio" is the card's highest-quality cue; commas add small breaks.
_DESC = ("{spk}'s voice is calm, clear and steady, at a moderate pace with a neutral narration tone, "
         "very clear audio, recorded very close with almost no background noise.")


def pick_speaker(lang: str, settings: dict | None) -> str:
    st = settings or {}
    names = st.get("speakers") or RECOMMENDED[lang]
    i = int(st.get("speaker", 0))
    return names[i] if 0 <= i < len(names) else names[0]


class IndicParlerEngine:
    name = "indic_parler"
    clones_voice = False
    uses_settings = True

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

    def synth(self, text: str, lang: str, ref_wav: Path | None, settings: dict | None = None) -> Wav:
        t = self._torch
        try:
            d = self._dtok(_DESC.format(spk=pick_speaker(lang, settings)), return_tensors="pt")
            p = self._tok(text, return_tensors="pt")
            t.manual_seed(1000 + int((settings or {}).get("seed", 0)))
            with t.no_grad():
                out = self._model.generate(
                    input_ids=d.input_ids, attention_mask=d.attention_mask,
                    prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
        except Exception as e:
            raise EngineUnavailable(f"indic_parler failed: {type(e).__name__}") from None
        return Wav(out.cpu().numpy().astype(np.float32).reshape(-1), int(self._model.config.sampling_rate))
