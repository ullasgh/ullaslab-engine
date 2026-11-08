"""narrate(): sentence-level synthesis with verbalised text, punctuation pauses, post-processing and the
naturalness gate (regenerate once, then flag). Same call shape as tts.tts so it drops into synth_segments."""
from __future__ import annotations
import logging
from pathlib import Path
from ..audio import Wav, normalize_loudness
from ..config import language
from ..tts import base
from .naturalness import score
from .post import postprocess
from .prosody import join_with_pauses, split_sentences
from .settings import voice_settings
from .textnorm import normalize_text

log = logging.getLogger("ullaslab.voice")


def resolve_ref(ref: Path | None, ref_clip: int) -> Path | None:
    """ref is a file; if sibling clips/clip<N>.wav exists (voice/clips/ in R2 layout) that clip wins."""
    if ref is None:
        return None
    ref = Path(ref)
    cand = ref.parent / "clips" / f"clip{ref_clip}.wav"
    return cand if cand.is_file() else ref


def _once(text: str, lang: str, ref: Path | None, engine: str | None, settings: dict) -> Wav:
    parts, eng = [], engine
    for sent, pause in split_sentences(text):
        w = base.tts(sent, lang, ref, normalize=False, engine=eng, settings=settings)
        eng = eng or w.engine
        parts.append((w, pause))
    out = join_with_pauses(parts)
    out.engine = eng
    return out


def narrate(text: str, lang: str, ref_wav: Path | str | None = None, *, normalize: bool = True,
            engine: str | None = None, gate: bool = True, overrides: dict | None = None) -> Wav:
    cfg = language(lang)
    st = voice_settings(lang, overrides)
    spoken = normalize_text(text, lang, cfg.get("number_format"))
    ref = resolve_ref(Path(ref_wav) if ref_wav else None, st["ref_clip"])
    flags: list[str] = []
    w = None
    for attempt in (0, 1):
        s = dict(st, seed=attempt, temperature=st["temperature"] * (0.85 if attempt else 1.0))
        w = _once(spoken, lang, ref, engine, s)
        w = postprocess(w)
        if not gate:
            break
        rep = score(w)
        if rep.passed:
            flags = []
            break
        log.warning("naturalness gate failed (%s) attempt %d: %s", lang, attempt, "; ".join(rep.failures))
        flags = [f"naturalness: {f}" for f in rep.failures]
    used = w.engine
    w = normalize_loudness(w) if normalize else w
    w.engine, w.flags = used, flags  # normalize_loudness builds a new Wav: keep the engine so synth_segments can pin it
    return w
