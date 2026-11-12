"""faster-whisper (MIT) transcription used for caption alignment and WER re-transcription."""
from __future__ import annotations
import os
from pathlib import Path

from .wer_norm import canonical_for_wer, merge_compounds, merge_names, proper_names
from .captions import NO_SPACE_LANGS

_MODEL = {}
# Style hint only (no script text): keeps the ASR from writing decimals as 5 ,550 and percentages as 525%, and spells the
# brand of the fixed sign-off ("Follow UllasLab. Education only.", in every video) the way the script does (WP8: Whisper
# wrote it as "Ullis lab", two word errors per video against the 3% WER gate).
_PROMPT = "The rate is 5.25 percent, up 0.5 percentage points. The ratio is 3.5%. Follow UllasLab. Education only."


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
    r, h = aligned_tokens(reference, hypothesis, lang)
    return 100 * jiwer.wer(" ".join(r), " ".join(h) or "_")


def aligned_tokens(reference: str, hypothesis: str, lang: str = "en") -> tuple[list[str], list[str]]:
    """The two token lists WER compares: canonical text, compounds and lexicon proper names merged. The ONE place that
    builds them, used by the voice gate (phase 2) and the final QA alike."""
    r, h = merge_compounds(canonical_for_wer(reference, lang).split(), canonical_for_wer(hypothesis, lang).split())
    return merge_names(r, h, proper_names(lang))


def wer_diff(reference: str, hypothesis: str, lang: str = "en", max_items: int = 40) -> list[str]:
    """Compact list of the differing tokens ("S ref->hyp", "I ->hyp", "D ref->") for the PRIVATE log: it quotes script text."""
    import jiwer
    r, h = aligned_tokens(reference, hypothesis, lang)
    if not r:
        return []
    o = jiwer.process_words(" ".join(r), " ".join(h) or "_")
    out = []
    for chunk in o.alignments[0]:
        if chunk.type == "equal":
            continue
        a, b = " ".join(r[chunk.ref_start_idx:chunk.ref_end_idx]), " ".join(h[chunk.hyp_start_idx:chunk.hyp_end_idx])
        out.append(f"{chunk.type[0].upper()} {a}->{b}")
    return out[:max_items]
