"""faster-whisper (MIT) transcription used for caption alignment and WER re-transcription."""
from __future__ import annotations
import os
from pathlib import Path

from .wer_norm import canonical_for_wer, merge_compounds
from .captions import NO_SPACE_LANGS

_MODEL = {}
# Style hint only (no script text): keeps the ASR from writing decimals as 5 ,550 and percentages as 525%.
_PROMPT = "The rate is 5.25 percent, up 0.5 percentage points. The ratio is 3.5%."


def model_size() -> str:
    return os.environ.get("ULLASLAB_ASR_MODEL", "large-v3")


def transcribe(path: Path, lang: str) -> list[tuple[str, float, float]]:
    """Word-level transcript [(word, start, end)]. Imports lazily; raises ImportError without the asr extra."""
    from faster_whisper import WhisperModel
    size = model_size()
    if size not in _MODEL:
        _MODEL[size] = WhisperModel(size, device="cpu", compute_type="int8")
    from .audio import Wav, resample
    audio = resample(Wav.load(path), 16000).samples  # decode ourselves: no dependency on PyAV decoding
    segs, _ = _MODEL[size].transcribe(audio, language=lang, word_timestamps=True, beam_size=5, initial_prompt=_PROMPT,
                                       vad_filter=False, condition_on_previous_text=False)
    out = []
    for s in segs:
        for w in (s.words or []):
            out.append((w.word.strip(), float(w.start), float(w.end)))
    return out


def words_by_segment(words: list[tuple[str, float, float]], timeline: dict, pad: float = 0.15) -> dict[str, list]:
    res: dict[str, list] = {s["id"]: [] for s in timeline["segments"]}
    for w in words:
        mid = (w[1] + w[2]) / 2
        for s in timeline["segments"]:
            if s["start"] - pad <= mid <= s["end"] + pad:
                res[s["id"]].append(w)
                break
    return res


def error_rate(reference: str, hypothesis: str, lang: str) -> float:
    """WER in percent (CER for languages written without spaces)."""
    import jiwer
    ref, hyp = canonical_for_wer(reference, lang), canonical_for_wer(hypothesis, lang)
    if not ref:
        return 0.0
    if lang in NO_SPACE_LANGS:
        return 100 * jiwer.cer(ref.replace(" ", ""), hyp.replace(" ", "") or "_")
    r, h = merge_compounds(ref.split(), hyp.split())
    return 100 * jiwer.wer(" ".join(r), " ".join(h) or "_")
