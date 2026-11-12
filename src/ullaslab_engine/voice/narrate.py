"""narrate(): sentence-level synthesis with verbalised text, punctuation pauses, post-processing and the
naturalness gate (regenerate once, then flag). Same call shape as tts.tts so it drops into synth_segments.

Long text (M2b fixes for the long-synthesis crash and the slow pace)
  - Chunks are sentences (long ones split at commas, prosody.MAX_WORDS). A sentence under MIN_WORDS words ("One.") is
    merged with its neighbour unless a pacing marker asks for the pause after it: very short inputs made the clone engine
    fail (an IndexError surfaced as NoVoiceAvailable) and lost the whole call.
  - Each chunk is retried with new seeds (CHUNK_RETRIES); if it still fails it is merged with the next chunk and tried
    again; only then does narrate() raise, naming the chunk.
  - With a cache directory (cache_dir= or ULLASLAB_TTS_CACHE) every finished chunk is stored under a key of its text,
    language, engine, settings, seed and reference-voice bytes, so a crash or a rerun resumes without losing work.
  - Joins are clean: each chunk's leading and trailing silence is trimmed, short fades remove clicks, and chunk levels are
    matched to their median (at most +-MAX_LEVEL_DB) before the pauses are inserted.
  - Pace: a target in words per minute (voice_defaults.pace in config/languages.yaml, default 150; a language entry may
    override it), both ways: a slow read gets shorter punctuation pauses (never below pause_floor of their length) and then
    a pitch-preserving tempo change (ffmpeg atempo) of at most max_speedup; a fast read gets longer pauses (at most
    pause_ceiling) and then a slow-down of at most max_slowdown. Explicit markers keep their pauses. The voice is not
    re-cloned or re-pitched. The achieved rate goes to Wav.meta["pace"]; a result still more than 10% under target adds a
    flag. The naturalness gate (pause_max_s, syllable_rate, ...) still checks the result."""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ..audio import Wav, normalize_loudness
from ..config import language
from ..tts import base
from .naturalness import score
from .post import postprocess
from .prosody import PAUSE_S, split_marked, strip_emphasis
from .settings import voice_settings
from .textnorm import normalize_text

log = logging.getLogger("ullaslab.voice")

MIN_WORDS = 3
CHUNK_RETRIES = 3          # attempts per chunk (seed, seed+100, seed+200) before merging with the next chunk
MAX_LEVEL_DB = 6.0
FADE_S = 0.008
TRIM_DB = -45.0
CHUNK_CACHE_VERSION = 1
PACE_DEFAULTS = {"target_wpm": 150, "max_speedup": 1.15, "pause_floor": 0.6, "max_slowdown": 1.15, "pause_ceiling": 1.6}
_UNSPACED = {"ja", "zh", "th"}
_SETTING_KEYS = ("exaggeration", "temperature", "effective_cfg_weight", "accent", "ref_clip", "speaker", "seed")


class Chunk:
    __slots__ = ("text", "pause", "keep")

    def __init__(self, text: str, pause: float, keep: bool):
        self.text, self.pause, self.keep = text, pause, keep

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return f"Chunk({self.text!r}, {self.pause}, {self.keep})"


def resolve_ref(ref: Path | None, ref_clip: int) -> Path | None:
    """ref is a file; if sibling clips/clip<N>.wav exists (voice/clips/ in R2 layout) that clip wins."""
    if ref is None:
        return None
    ref = Path(ref)
    cand = ref.parent / "clips" / f"clip{ref_clip}.wav"
    return cand if cand.is_file() else ref


def _words(text: str, lang: str) -> int:
    if lang in _UNSPACED:
        return max(1, len(re.sub(r"\s", "", text)) // 2)
    return len(re.findall(r"\w+", text))


def plan_chunks(text: str, lang: str = "en") -> list[Chunk]:
    """Sentences (and comma pieces of long ones) with their pauses; pieces under MIN_WORDS words are merged into the next
    one (the last into the previous) unless a marker asked for the pause after them."""
    out: list[Chunk] = []
    carry: Chunk | None = None
    for t, p, k in split_marked(text):
        c = Chunk(t, p, k)
        if carry is not None:
            c = Chunk(carry.text + " " + c.text, c.pause, c.keep)
            carry = None
        if _words(c.text, lang) < MIN_WORDS and not c.keep:
            if c.pause >= PAUSE_S["para"] and out and not out[-1].keep:   # ends a paragraph: join backwards, keep the break
                out[-1] = Chunk(out[-1].text + " " + c.text, c.pause, c.keep)
                continue
            carry = c
            continue
        out.append(c)
    if carry is not None:
        if out and not out[-1].keep:
            out[-1] = Chunk(out[-1].text + " " + carry.text, carry.pause, carry.keep)
        else:
            out.append(carry)
    return out


# ------------------------------------------------------------------ chunk cache
def _ref_sha(ref: Path | None) -> str:
    if ref is None or not Path(ref).is_file():
        return "none"
    return hashlib.sha256(Path(ref).read_bytes()).hexdigest()


def chunk_key(text: str, lang: str, engine: str | None, settings: dict, ref_sha: str) -> str:
    blob = json.dumps({"v": CHUNK_CACHE_VERSION, "text": text, "lang": lang, "engine": engine or "auto", "ref": ref_sha,
                       "settings": {k: settings.get(k) for k in _SETTING_KEYS}}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_dir(cache_dir: Path | str | None) -> Path | None:
    d = cache_dir or os.environ.get("ULLASLAB_TTS_CACHE")
    return Path(d) if d else None


def _cache_get(d: Path | None, key: str) -> Wav | None:
    if d is None:
        return None
    wav, meta = d / f"{key}.wav", d / f"{key}.json"
    if not (wav.is_file() and meta.is_file()):
        return None
    try:
        info = json.loads(meta.read_text())
        x, sr = sf.read(str(wav), dtype="float32")
    except (OSError, ValueError, RuntimeError):
        return None
    if len(x) != info.get("samples"):
        return None                          # partial write: synthesise again
    return Wav(np.asarray(x, dtype=np.float32), sr, info.get("engine"))


def _cache_put(d: Path | None, key: str, w: Wav) -> None:
    if d is None:
        return
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{key}.part.wav"
    sf.write(str(tmp), w.samples, w.sr, subtype="FLOAT")
    (d / f"{key}.json").write_text(json.dumps({"engine": w.engine, "samples": len(w.samples), "sr": w.sr}))
    tmp.replace(d / f"{key}.wav")


# ------------------------------------------------------------------ synthesis
def _synth(text: str, lang: str, ref: Path | None, engine: str | None, settings: dict, cache: Path | None, ref_sha: str) -> Wav:
    """One chunk, with retries on new seeds. Raises base.NoVoiceAvailable when every attempt fails."""
    last: Exception | None = None
    for k in range(CHUNK_RETRIES):
        st = dict(settings, seed=int(settings.get("seed", 0)) + 100 * k)
        key = chunk_key(text, lang, engine, st, ref_sha)
        hit = _cache_get(cache, key)
        if hit is not None:
            return hit
        try:
            w = base.tts(text, lang, ref, normalize=False, engine=engine, settings=st)
        except base.NoVoiceAvailable as e:
            last = e
            log.warning("chunk failed (attempt %d/%d): %r: %s", k + 1, CHUNK_RETRIES, text[:60], e)
            continue
        _cache_put(cache, key, w)
        return w
    raise base.NoVoiceAvailable(f"chunk {text[:80]!r} failed {CHUNK_RETRIES} times: {last}")


def _trim(x: np.ndarray, sr: int) -> np.ndarray:
    """Remove leading/trailing silence relative to the chunk's own peak, keep 30 ms of air, fade the edges."""
    n = max(1, int(0.01 * sr))
    k = len(x) // n
    if k == 0:
        return x.astype(np.float32)
    rms = np.sqrt((x[: k * n].reshape(k, n).astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    on = np.flatnonzero(db > max(db.max() + TRIM_DB, -70.0))
    if len(on) == 0:
        return x.astype(np.float32)
    keep = int(0.03 * sr)
    y = x[max(0, on[0] * n - keep): min(len(x), (on[-1] + 1) * n + keep)].astype(np.float32).copy()
    f = min(len(y) // 2, int(FADE_S * sr))
    if f > 1:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        y[:f] *= ramp
        y[-f:] *= ramp[::-1]
    return y


def _active_db(x: np.ndarray, sr: int) -> float:
    n = max(1, int(0.02 * sr))
    k = len(x) // n
    if k == 0:
        return -70.0
    rms = np.sqrt((x[: k * n].reshape(k, n).astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    act = db[db > db.max() - 20]
    return float(10 * np.log10(np.mean(10 ** (act / 10)))) if len(act) else -70.0


def level_match(chunks: list[np.ndarray], sr: int) -> list[np.ndarray]:
    """Bring each chunk's active-speech level to the median of all chunks (bounded), so joins do not jump in loudness."""
    lv = [_active_db(c, sr) for c in chunks]
    ref = float(np.median(lv)) if lv else 0.0
    return [(c * np.float32(10 ** (np.clip(ref - v, -MAX_LEVEL_DB, MAX_LEVEL_DB) / 20))).astype(np.float32) for c, v in zip(chunks, lv)]


def atempo(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Pitch-preserving tempo change (ffmpeg atempo, local, free). factor > 1 is faster."""
    if abs(factor - 1.0) < 1e-3 or len(x) == 0:
        return x
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(a), x, sr, subtype="FLOAT")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(a), "-af", f"atempo={factor:.4f}", "-ar", str(sr),
                            "-c:a", "pcm_f32le", str(b)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"atempo failed: {r.stderr[-200:]}")
        y, _ = sf.read(str(b), dtype="float32")
    return np.asarray(y, dtype=np.float32).reshape(-1)


def pace_settings(lang: str, overrides: dict | None = None) -> dict:
    from .settings import voice_defaults
    p = {**PACE_DEFAULTS, **(voice_defaults().get("pace") or {}), **(language(lang).get("pace") or {}),
         **((overrides or {}).get("pace") or {})}
    p["target_wpm"] = float(p["target_wpm"] or 0)
    p["max_speedup"] = max(1.0, float(p["max_speedup"]))
    p["pause_floor"] = min(1.0, max(0.0, float(p["pause_floor"])))
    p["max_slowdown"] = max(1.0, float(p["max_slowdown"]))
    p["pause_ceiling"] = max(1.0, float(p["pause_ceiling"]))
    return p


def fit_pace(chunks: list[np.ndarray], pauses: list[float], keep: list[bool], words: int, sr: int,
             pace: dict) -> tuple[list[np.ndarray], list[float], dict]:
    """Bring words / total time to target_wpm, both ways and bounded. Too slow: shorten punctuation pauses (not below
    pause_floor), then speed speech up (at most max_speedup). Too fast (WP8: Chatterbox read the fixture at 172-183 wpm on
    the Actions runner, past the A3 limit of 175): lengthen punctuation pauses (at most pause_ceiling), then slow speech
    down (at most max_slowdown). Explicit markers keep their pauses. Pitch is kept (ffmpeg atempo)."""
    speech = sum(len(c) for c in chunks) / sr
    total = speech + sum(pauses)
    info = {"target_wpm": pace["target_wpm"], "raw_wpm": round(words / total * 60, 1) if total else 0.0, "speedup": 1.0, "pause_scale": 1.0}
    tgt = pace["target_wpm"]
    if not tgt or not words or total <= 0 or abs(words / total * 60 - tgt) < 0.5:
        info["wpm"] = info["raw_wpm"]
        return chunks, pauses, info
    want = words / tgt * 60                       # seconds the narration should take
    if total < want:                              # too fast: longer pauses first, then slower speech
        soft = sum(p for p, k in zip(pauses, keep) if not k)
        fixed = sum(pauses) - soft
        if soft > 0:
            scale = min(pace["pause_ceiling"], max(1.0, (want - speech - fixed) / soft))
            pauses = [p if k else p * scale for p, k in zip(pauses, keep)]
            info["pause_scale"] = round(scale, 3)
        rest = want - sum(pauses)
        if rest > speech:
            f = max(1.0 / pace["max_slowdown"], speech / rest)
            chunks = [atempo(c, sr, f) for c in chunks]
            info["speedup"] = round(f, 3)
        total = sum(len(c) for c in chunks) / sr + sum(pauses)
        info["wpm"] = round(words / total * 60, 1)
        return chunks, pauses, info
    soft = sum(p for p, k in zip(pauses, keep) if not k)
    fixed = sum(pauses) - soft
    if soft > 0:
        scale = max(pace["pause_floor"], min(1.0, (want - speech - fixed) / soft))
        pauses = [p if k else p * scale for p, k in zip(pauses, keep)]
        info["pause_scale"] = round(scale, 3)
    rest = want - sum(pauses)
    if speech > rest > 0 or (rest <= 0 < speech):
        f = pace["max_speedup"] if rest <= 0 else min(pace["max_speedup"], speech / rest)
        chunks = [atempo(c, sr, f) for c in chunks]
        info["speedup"] = round(f, 3)
    total = sum(len(c) for c in chunks) / sr + sum(pauses)
    info["wpm"] = round(words / total * 60, 1)
    return chunks, pauses, info


def _once(text: str, lang: str, ref: Path | None, engine: str | None, settings: dict, cache: Path | None = None,
          pace: dict | None = None) -> Wav:
    plan = plan_chunks(text, lang)
    if not plan:
        raise ValueError("nothing to narrate")
    ref_sha = _ref_sha(ref)
    waves: list[Wav] = []
    eng = engine
    i = 0
    while i < len(plan):
        c = plan[i]
        try:
            w = _synth(c.text, lang, ref, eng, settings, cache, ref_sha)
        except base.NoVoiceAvailable:
            if i + 1 < len(plan):            # last resort: say it together with the next chunk
                log.warning("merging failed chunk %r into the next one", c.text[:60])
                plan[i + 1] = Chunk(c.text + " " + plan[i + 1].text, plan[i + 1].pause, plan[i + 1].keep)
                del plan[i]
                continue
            raise
        eng = eng or w.engine
        waves.append(w)
        i += 1
    sr = waves[0].sr
    if any(w.sr != sr for w in waves):
        raise ValueError("sample-rate mismatch between chunks")
    parts = level_match([_trim(w.samples, sr) for w in waves], sr)
    pauses = [c.pause for c in plan]
    info = None
    if pace is not None:
        parts, pauses, info = fit_pace(parts, pauses, [c.keep for c in plan], _words(" ".join(c.text for c in plan), lang), sr, pace)
    out = []
    for x, p in zip(parts, pauses):
        out.append(x)
        if p > 0:
            out.append(np.zeros(int(round(p * sr)), dtype=np.float32))
    w = Wav(np.concatenate(out).astype(np.float32), sr, eng)
    if info is not None:
        w.meta["pace"] = info
    w.meta["chunks"] = len(plan)
    return w


_MARKER = re.compile(r"(\[\[[^\[\]]*\]\])")


def spoken_text(text: str, lang: str, number_format: str | None = None) -> str:
    """Lexicon and verbalisation for the words only: pacing markers ([[pause:0.8]] ...) pass through untouched, so their
    numbers are never verbalised into words that would be spoken. Emphasis asterisks are dropped."""
    parts = _MARKER.split(strip_emphasis(text))
    return "".join(p if i % 2 else normalize_text(p, lang, number_format) for i, p in enumerate(parts))


def narrate(text: str, lang: str, ref_wav: Path | str | None = None, *, normalize: bool = True,
            engine: str | None = None, gate: bool = True, overrides: dict | None = None,
            cache_dir: Path | str | None = None, pace: bool = True) -> Wav:
    cfg = language(lang)
    st = voice_settings(lang, {k: v for k, v in (overrides or {}).items() if k != "pace"})
    spoken = spoken_text(text, lang, cfg.get("number_format"))
    ref = resolve_ref(Path(ref_wav) if ref_wav else None, st["ref_clip"])
    pc = pace_settings(lang, overrides) if pace else None
    cache = _cache_dir(cache_dir)
    flags: list[str] = []
    w = None
    for attempt in (0, 1):
        s = dict(st, seed=int(st.get("seed", 0)) + attempt, temperature=st["temperature"] * (0.85 if attempt else 1.0))
        w = _once(spoken, lang, ref, engine, s, cache, pc)
        meta = dict(w.meta)
        w = postprocess(w)
        w.meta = meta
        if not gate:
            break
        rep = score(w)
        if rep.passed:
            flags = []
            break
        log.warning("naturalness gate failed (%s) attempt %d: %s", lang, attempt, "; ".join(rep.failures))
        flags = [f"naturalness: {f}" for f in rep.failures]
    used, meta = w.engine, dict(w.meta)
    p = meta.get("pace")
    if p and p["target_wpm"] and p["wpm"] < 0.9 * p["target_wpm"]:
        flags.append(f"pace: {p['wpm']} wpm is more than 10% under the {p['target_wpm']:.0f} wpm target "
                     f"(max speed-up {pc['max_speedup']} reached); shorten pauses in the script or raise max_speedup")
    if p and p["target_wpm"] and p["wpm"] > 1.1 * p["target_wpm"]:
        flags.append(f"pace: {p['wpm']} wpm is more than 10% over the {p['target_wpm']:.0f} wpm target "
                     f"(max slow-down {pc['max_slowdown']} reached)")
    w = normalize_loudness(w) if normalize else w
    w.engine, w.flags, w.meta = used, flags, meta  # normalize_loudness builds a new Wav: keep the engine so synth_segments can pin it
    return w
