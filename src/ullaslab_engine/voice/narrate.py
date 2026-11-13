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
    a pitch-preserving tempo change (ffmpeg atempo) of at most max_speedup; a fast read gets a slow-down of at most
    max_slowdown and then longer pauses (at most pause_ceiling, never past PAUSE_CAP_S). Explicit markers keep their pauses. The voice is not
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
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from ..audio import Wav, normalize_loudness
from ..config import language
from ..tts import base
from .delivery import load_options, load_profile, synth_overrides, take_delivery, default_profile
from .naturalness import score
from .post import postprocess
from .prosody import PAUSE_S, split_marked, strip_emphasis
from .settings import voice_settings
from .takes import TAKE_SEED_STEP, Take, pitch_metrics, select_all
from .textnorm import normalize_text

log = logging.getLogger("ullaslab.voice")

MIN_WORDS = 3
CHUNK_RETRIES = 3          # attempts per chunk (seed, seed+100, seed+200) before merging with the next chunk
MAX_LEVEL_DB = 6.0
FADE_S = 0.008
TRIM_DB = -45.0
CHUNK_CACHE_VERSION = 1
MAX_EXTRA_LINES = 4        # a WER retry adds a take to at most this many lines
PACE_DEFAULTS = {"target_wpm": 150, "max_speedup": 1.15, "pause_floor": 0.6, "max_slowdown": 1.15, "pause_ceiling": 1.3}
PAUSE_CAP_S = 0.55  # longest pause the slow-down may create (A3 max_silence_s 1.2 s also counts trimmed chunk edges)
_UNSPACED = {"ja", "zh", "th"}
_SETTING_KEYS = ("exaggeration", "temperature", "effective_cfg_weight", "accent", "ref_clip", "speaker", "seed")
_TEMP_FACTOR = "temp_factor"   # the naturalness retry's 0.85 on the base temperature; kept when a tag sets its own


class Chunk:
    __slots__ = ("text", "pause", "keep", "delivery")

    def __init__(self, text: str, pause: float, keep: bool, delivery: str | None = None):
        self.text, self.pause, self.keep, self.delivery = text, pause, keep, delivery

    def __repr__(self) -> str:   # pragma: no cover - debugging aid
        return f"Chunk({self.text!r}, {self.pause}, {self.keep}, {self.delivery})"


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
    sticky: str | None = None
    for t, p, k in split_marked(text):
        t, tag, sticky = take_delivery(t, sticky)      # delivery markers ([[d:tag]]) never reach the engine or the word count
        c = Chunk(t, p, k, tag)
        if carry is not None:
            c = Chunk(carry.text + " " + c.text, c.pause, c.keep, carry.delivery)
            carry = None
        if _words(c.text, lang) < MIN_WORDS and not c.keep:
            if c.pause >= PAUSE_S["para"] and out and not out[-1].keep:   # ends a paragraph: join backwards, keep the break
                out[-1] = Chunk(out[-1].text + " " + c.text, c.pause, c.keep, out[-1].delivery)
                continue
            carry = c
            continue
        out.append(c)
    if carry is not None:
        if out and not out[-1].keep:
            out[-1] = Chunk(out[-1].text + " " + carry.text, carry.pause, carry.keep, out[-1].delivery)
        else:
            out.append(carry)
    return out


# ------------------------------------------------------------------ chunk cache
def _ref_sha(ref: Path | None) -> str:
    if ref is None or not Path(ref).is_file():
        return "none"
    return hashlib.sha256(Path(ref).read_bytes()).hexdigest()


def chunk_key(text: str, lang: str, engine: str | None, settings: dict, ref_sha: str) -> str:
    keyed = {k: settings.get(k) for k in _SETTING_KEYS}
    if settings.get("t3_weights") not in (None, "v2"):      # v2 keys stay exactly what they were before the V3 weights existed
        keyed["t3_weights"] = settings["t3_weights"]
    blob = json.dumps({"v": CHUNK_CACHE_VERSION, "text": text, "lang": lang, "engine": engine or "auto", "ref": ref_sha,
                       "settings": keyed}, sort_keys=True, ensure_ascii=False)
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
            hit.meta["chunk_key"] = key
            return hit
        try:
            w = base.tts(text, lang, ref, normalize=False, engine=engine, settings=st)
        except base.NoVoiceAvailable as e:
            last = e
            log.warning("chunk failed (attempt %d/%d): %r: %s", k + 1, CHUNK_RETRIES, text[:60], e)
            continue
        _cache_put(cache, key, w)
        w.meta["chunk_key"] = key
        return w
    raise base.NoVoiceAvailable(f"chunk {text[:80]!r} failed {CHUNK_RETRIES} times: {last}", getattr(last, "failures", None))


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


def pace_settings(lang: str, overrides: dict | None = None, profile_pace: dict | None = None) -> dict:
    """voice_defaults.pace < the language's pace < the delivery profile's pace options (pause_floor) < the caller's overrides."""
    from .settings import voice_defaults
    p = {**PACE_DEFAULTS, **(voice_defaults().get("pace") or {}), **(language(lang).get("pace") or {}),
         **(profile_pace or {}), **((overrides or {}).get("pace") or {})}
    p["target_wpm"] = float(p["target_wpm"] or 0)
    p["max_speedup"] = max(1.0, float(p["max_speedup"]))
    p["pause_floor"] = min(1.0, max(0.0, float(p["pause_floor"])))
    p["max_slowdown"] = max(1.0, float(p["max_slowdown"]))
    p["pause_ceiling"] = max(1.0, float(p["pause_ceiling"]))
    p["words"] = int(p.get("words") or 0)
    return p


def cap_inner_silence(x: np.ndarray, sr: int, cap_s: float = PAUSE_CAP_S, thresh_db: float = -45.0,
                      frame_s: float = 0.02) -> np.ndarray:
    """Shorten every silent run inside a chunk (same -45 dB / 20 ms frames as the A3 max_silence_s measure) to cap_s.
    Used after a slow-down, which stretches the engine's own mid-sentence pauses along with the speech."""
    f = max(1, int(sr * frame_s))
    n = len(x) // f
    if n < 3:
        return x
    rms = np.sqrt(np.mean(x[: n * f].astype(np.float64).reshape(n, f) ** 2, axis=1))
    silent = rms < 10 ** (thresh_db / 20)
    keep_frames = int(cap_s / frame_s)
    out, i = [], 0
    while i < n:
        j = i
        while j < n and silent[j] == silent[i]:
            j += 1
        a, b = i * f, j * f
        if silent[i] and 0 < i and j < n and (j - i) > keep_frames:   # inner runs only; edges are trimmed elsewhere
            h = keep_frames * f // 2
            out += [x[a: a + h], x[b - h: b]]
        else:
            out.append(x[a:b])
        i = j
    out.append(x[n * f:])
    return np.concatenate(out).astype(x.dtype)


def fit_pace(chunks: list[np.ndarray], pauses: list[float], keep: list[bool], words: int, sr: int,
             pace: dict) -> tuple[list[np.ndarray], list[float], dict]:
    """Bring words / total time to target_wpm, both ways and bounded. Too slow: shorten punctuation pauses (not below
    pause_floor), then speed speech up (at most max_speedup). Too fast (WP8: Chatterbox read the fixture at 172-183 wpm on
    the Actions runner, past the A3 limit of 175): slow speech down (at most max_slowdown), then lengthen punctuation
    pauses (at most pause_ceiling, never past PAUSE_CAP_S). Explicit markers keep their pauses. Pitch is kept (ffmpeg atempo)."""
    speech = sum(len(c) for c in chunks) / sr
    total = speech + sum(pauses)
    info = {"target_wpm": pace["target_wpm"], "raw_wpm": round(words / total * 60, 1) if total else 0.0, "speedup": 1.0, "pause_scale": 1.0}
    tgt = pace["target_wpm"]
    if not tgt or not words or total <= 0 or abs(words / total * 60 - tgt) < 0.5:
        info["wpm"] = info["raw_wpm"]
        return chunks, pauses, info
    want = words / tgt * 60                       # seconds the narration should take
    if total < want:                              # too fast: slower speech first, then longer pauses (each capped)
        f = max(1.0 / pace["max_slowdown"], min(1.0, speech / max(want - sum(pauses), 1e-6)))
        if f < 0.999:
            chunks = [cap_inner_silence(atempo(c, sr, f), sr) for c in chunks]
            info["speedup"] = round(f, 3)
        speech = sum(len(c) for c in chunks) / sr
        soft = sum(p for p, k in zip(pauses, keep) if not k)
        fixed = sum(pauses) - soft
        if soft > 0 and speech + sum(pauses) < want:
            scale = min(pace["pause_ceiling"], (want - speech - fixed) / soft)
            # a lengthened pause never passes PAUSE_CAP_S (A3 max_silence_s is 1.2 s; ASR word edges add to the gap)
            pauses = [p if k or p <= 0 else max(p, min(p * scale, PAUSE_CAP_S)) for p, k in zip(pauses, keep)]
            info["pause_scale"] = round(scale, 3)
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


def apply_delivery(parts: list[np.ndarray], pauses: list[float], keeps: list[bool], tags: list[str | None],
                   profile: dict[str, dict], sr: int):
    """Per-tag tempo, gain and pauses on the joined-up chunks, before the pacer fits the whole read to its wpm target (the
    pacer keeps pauses marked `keep`, and scales every chunk's tempo alike, so the differences between lines survive).
    Returns (parts, pauses, keeps, {tag: lines}). Lines without a tag or a profile entry are left exactly as they are."""
    parts, pauses, keeps = list(parts), list(pauses), list(keeps)
    used: dict[str, int] = {}
    for i, tag in enumerate(tags):
        st = profile.get(tag or "")
        if not st:
            continue
        used[tag] = used.get(tag, 0) + 1
        if st.get("tempo", 1.0) != 1.0:
            parts[i] = atempo(parts[i], sr, st["tempo"])
        if st.get("gain_db"):
            parts[i] = (parts[i] * np.float32(10 ** (st["gain_db"] / 20))).astype(np.float32)
        if st.get("pause_before", 0) > 0 and i > 0:
            pauses[i - 1] = max(pauses[i - 1], st["pause_before"])
            keeps[i - 1] = True
        if st.get("pause_after", 0) > 0 and i + 1 < len(parts):   # the last line has no pause after it
            pauses[i] = max(pauses[i], st["pause_after"])
            keeps[i] = True
    return parts, pauses, keeps, used


def _chunk_settings(settings: dict, tag: str | None, profile: dict | None, lang: str) -> dict:
    """Global settings overlaid with the tag's synthesis settings (profile None or no tag: unchanged)."""
    if not profile or not tag:
        return settings
    forced = settings.get("accent") == "native" and lang != "en"      # upstream: native accent on a non-English target => cfg 0
    ov = synth_overrides(tag, profile, cfg_forced=forced)
    if "temperature" in ov:
        ov["temperature"] = ov["temperature"] * float(settings.get(_TEMP_FACTOR, 1.0))
    return dict(settings, **ov)


def default_take_check(text: str, w: Wav, lang: str) -> float:
    """Per-line accuracy of one take: WER percent of the ASR transcript against the line text, with the voice gate's own
    transcriber and canonicalisation (asr.transcribe / asr.error_rate)."""
    from ..asr import error_rate, transcribe
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "take.wav"
        w.save(p)
        words = transcribe(p, lang)
    return float(error_rate(text, " ".join(x[0] for x in words), lang))


def _take_metrics(cache: Path | None, w: Wav, text: str, lang: str, check, measure,
                  speed: float = 1.0) -> tuple[float, float, float, float]:
    """(wer, duration, pitch spread, artefact share) of a take. The ASR check runs on the take at the speed it will be heard at
    (`speed`: the line's tempo times the pacer's estimated speed-up), because a take that reads cleanly at natural speed can
    mis-read a word once the pacer has sped the read up. Records sit next to the chunk cache, one per (take, speed), so a
    resumed run or a WER retry never transcribes the same take at the same speed again. The ASR model size is part of the record."""
    from ..asr import model_size
    key, side, rec = w.meta.get("chunk_key"), None, {}
    tag = f"{speed:.2f}"
    th = hashlib.sha256(text.encode()).hexdigest()
    if cache is not None and key:
        side = cache / f"{key}.take.json"
        if side.is_file():
            try:
                rec = json.loads(side.read_text())
                if rec.get("asr") != model_size() or rec.get("text") != th or "speeds" not in rec:
                    rec = {}
                elif tag in rec["speeds"]:
                    r = rec["speeds"][tag]
                    return r["wer"], rec["dur"], rec["pitch"], rec["art"]
            except (OSError, ValueError, KeyError):
                rec = {}
    t = _trim(w.samples, w.sr)
    heard = Wav(atempo(t, w.sr, speed), w.sr) if abs(speed - 1.0) > 0.004 else Wav(t, w.sr)
    wer = float(check(text, heard, lang))
    if "pitch" in rec:
        pitch, art = rec["pitch"], rec["art"]
    else:
        pitch, art = measure(t, w.sr)
    out = (wer, len(t) / w.sr, pitch, art)
    if side is not None:
        rec = {"asr": model_size(), "text": th, "dur": out[1], "pitch": pitch, "art": art,
               "speeds": {**(rec.get("speeds") or {}), tag: {"wer": wer}}}
        side.write_text(json.dumps(rec))
    return out


def _culprit_lines(plan: list[Chunk], words: list[str], lang: str) -> list[int]:
    """Lines whose text contains a reference word the last file-level WER check mis-heard (canonical tokens)."""
    from ..wer_norm import canonical_for_wer
    ws = set(words or [])
    return [i for i, c in enumerate(plan) if ws & set(canonical_for_wer(c.text, lang).split())] if ws else []


def _extra_lines(cands: list[list[Take]], plan: list[Chunk], attempt: int, lang: str, culprits: list[int] | None = None) -> list[int]:
    """Lines that get one more take on a WER retry (attempt >= 1): the ones whose best take still has word errors, worst first;
    when no line has a recorded error (the miss came from the joins, not a line) the fastest-spoken lines, whose words are the
    likeliest to blur once the read is sped up. At most MAX_EXTRA_LINES; none on the first attempt."""
    if attempt <= 0:
        return []
    if culprits:
        return culprits[:MAX_EXTRA_LINES]
    def best(ts):
        return min(t.wer for t in ts)
    bad = sorted((i for i, ts in enumerate(cands) if best(ts) > 0), key=lambda i: -best(cands[i]))
    if bad:
        return bad[:MAX_EXTRA_LINES]
    def rate(i):
        d = max(t.dur for t in cands[i]) or 1.0
        return _words(plan[i].text, lang) / d
    return sorted(range(len(cands)), key=lambda i: -rate(i))[:MAX_EXTRA_LINES]


def _once(text: str, lang: str, ref: Path | None, engine: str | None, settings: dict, cache: Path | None = None,
          pace: dict | None = None, profile: dict | None = None, takes: int = 1, take_check=None,
          take_measure=None, attempt: int = 0, culprit_words: list[str] | None = None) -> Wav:
    plan = plan_chunks(text, lang)
    if not plan:
        raise ValueError("nothing to narrate")
    ref_sha = _ref_sha(ref)
    waves: list[Wav] = []
    tstats = {"check_s": 0.0, "asr_calls": 0}
    check, measure = take_check or default_take_check, take_measure or pitch_metrics
    tseed = int(settings.get("take_seed", settings.get("seed", 0)))
    eng = engine
    i = 0
    while i < len(plan):                    # take 0 of every line (the only take when takes == 1)
        c = plan[i]
        st = _chunk_settings(settings, c.delivery, profile, lang)
        if takes > 1:
            st = dict(st, seed=tseed)
        try:
            w = _synth(c.text, lang, ref, eng, st, cache, ref_sha)
        except base.NoVoiceAvailable:
            if i + 1 < len(plan):            # last resort: say it together with the next chunk
                log.warning("merging failed chunk %r into the next one", c.text[:60])
                plan[i + 1] = Chunk(c.text + " " + plan[i + 1].text, plan[i + 1].pause, plan[i + 1].keep, c.delivery)
                del plan[i]
                continue
            raise
        eng = eng or w.engine
        waves.append(w)
        i += 1
    take_info = None
    if takes > 1 and eng == "chatterbox":
        sr0 = waves[0].sr
        # the pacer's speed change is known (about) before the extra takes: fit it on the first takes, so every take is checked
        # at the speed it will be heard at (line tempo x the global factor)
        tp, tpa, tk, _u = (level_match([_trim(w.samples, sr0) for w in waves], sr0), [c.pause for c in plan], [c.keep for c in plan], {})
        if profile:
            tp, tpa, tk, _u = apply_delivery(tp, tpa, tk, [c.delivery for c in plan], profile, sr0)
        glob = 1.0
        if pace is not None:
            glob = fit_pace(tp, tpa, tk, pace.get("words") or _words(" ".join(c.text for c in plan), lang), sr0, pace)[2]["speedup"]

        def speed_of(c: Chunk) -> float:
            return glob * float((profile or {}).get(c.delivery or "", {}).get("tempo", 1.0))

        def take(i: int, j: int) -> Take | None:
            c = plan[i]
            st = dict(_chunk_settings(settings, c.delivery, profile, lang), seed=tseed + TAKE_SEED_STEP * j)
            try:
                w = waves[i] if j == 0 else _synth(c.text, lang, ref, eng, st, cache, ref_sha)
            except base.NoVoiceAvailable:
                log.warning("take %d failed for a chunk; skipped", j + 1)
                return None
            t0 = time.time()
            wer, dur, pitch, art = _take_metrics(cache, w, c.text, lang, check, measure, speed_of(c))
            tstats["check_s"] += time.time() - t0
            tstats["asr_calls"] += 1
            return Take(st["seed"], wer, dur, pitch, art, w)
        cands = [[t for t in (take(k, j) for j in range(takes)) if t] for k in range(len(plan))]
        cl = _culprit_lines(plan, culprit_words, lang)
        fresh: dict[int, list[Take]] = {}
        for k in _extra_lines(cands, plan, attempt, lang, cl):   # WER retry: one new take for each culprit/worst line, then re-select
            for j in range(takes, takes + attempt):
                t = take(k, j)
                if t:
                    cands[k].append(t)
                    if j == takes + attempt - 1:
                        fresh[k] = [t]
        pick = select_all(cands)
        for k in cl:                         # a line holding a word the file check mis-heard: the takes already heard failed it in
            if k in fresh and fresh[k][0].wer <= min(t.wer for t in cands[k]):      # context, so use this attempt's new take
                pick[k] = cands[k].index(fresh[k][0])
        waves = [ts[k].wave for ts, k in zip(cands, pick)]
        kept = [ts[k] for ts, k in zip(cands, pick)]
        every = [t for ts in cands for t in ts]
        take_info = {"takes": takes, "lines": len(cands), "check_s": round(tstats["check_s"], 1), "asr_calls": tstats["asr_calls"],
                     "speed_est": round(glob, 3), "pitch_kept": round(float(np.mean([t.pitch for t in kept])), 2),
                     "pitch_all": round(float(np.mean([t.pitch for t in every])), 2),
                     "first_take_chosen": sum(1 for k in pick if k == 0), "line_wer_kept": [round(t.wer, 1) for t in kept]}
    sr = waves[0].sr
    if any(w.sr != sr for w in waves):
        raise ValueError("sample-rate mismatch between chunks")
    parts = level_match([_trim(w.samples, sr) for w in waves], sr)
    pauses = [c.pause for c in plan]
    keeps = [c.keep for c in plan]
    used_tags: dict[str, int] = {}
    if profile:
        parts, pauses, keeps, used_tags = apply_delivery(parts, pauses, keeps, [c.delivery for c in plan], profile, sr)
    info = None
    if pace is not None:
        # words: the count the A3 wpm gate will use (whitespace tokens of the script text, see studio/actions.make_voices);
        # without it the spoken words after number verbalisation ("4.95" is four words) are counted, which reads a
        # number-heavy script 15-20% faster than the gate measures it
        parts, pauses, info = fit_pace(parts, pauses, keeps,
                                       pace.get("words") or _words(" ".join(c.text for c in plan), lang), sr, pace)
    out = []
    for x, p in zip(parts, pauses):
        out.append(x)
        if p > 0:
            out.append(np.zeros(int(round(p * sr)), dtype=np.float32))
    w = Wav(np.concatenate(out).astype(np.float32), sr, eng)
    if info is not None:
        w.meta["pace"] = info
    w.meta["chunks"] = len(plan)
    if used_tags:
        w.meta["delivery"] = used_tags
    if take_info:
        w.meta["takes"] = take_info
    return w


_MARKER = re.compile(r"(\[\[[^\[\]]*\]\])")


def spoken_text(text: str, lang: str, number_format: str | None = None) -> str:
    """Lexicon and verbalisation for the words only: pacing markers ([[pause:0.8]] ...) pass through untouched, so their
    numbers are never verbalised into words that would be spoken. Emphasis asterisks are dropped."""
    parts = _MARKER.split(strip_emphasis(text))
    return "".join(p if i % 2 else normalize_text(p, lang, number_format) for i, p in enumerate(parts))


def narrate(text: str, lang: str, ref_wav: Path | str | None = None, *, normalize: bool = True,
            engine: str | None = None, gate: bool = True, overrides: dict | None = None,
            cache_dir: Path | str | None = None, pace: bool = True, take_check=None, take_measure=None) -> Wav:
    cfg = language(lang)
    st = voice_settings(lang, {k: v for k, v in (overrides or {}).items() if k not in ("pace", "delivery_profile", "takes", "take_seed", "attempt", "culprit_words")})
    spoken = spoken_text(text, lang, cfg.get("number_format"))
    ref = resolve_ref(Path(ref_wav) if ref_wav else None, st["ref_clip"])
    prof_name = (overrides or {}).get("delivery_profile") or default_profile(lang)
    profile = load_profile(prof_name) or None          # `baseline` = {} = the behaviour before profiles existed
    opts = load_options(prof_name)                     # whole-read options of the profile: takes, T3 weights, pause floor
    takes = int((overrides or {}).get("takes") or opts.get("takes", 1))
    if "pause_floor" in opts:
        opts_pace = {"pause_floor": opts["pause_floor"]}
    else:
        opts_pace = None
    pc = pace_settings(lang, overrides, opts_pace) if pace else None
    cache = _cache_dir(cache_dir)
    flags: list[str] = []
    w = None
    for attempt in (0, 1):
        s = dict(st, seed=int(st.get("seed", 0)) + attempt, temperature=st["temperature"] * (0.85 if attempt else 1.0))
        if profile:
            s[_TEMP_FACTOR] = 0.85 if attempt else 1.0
        if opts.get("t3_weights"):
            s["t3_weights"] = opts["t3_weights"]
        if (overrides or {}).get("take_seed") is not None:      # takes keep their seeds across WER retries: the cache reuses them
            s["take_seed"] = int(overrides["take_seed"]) + attempt
        w = _once(spoken, lang, ref, engine, s, cache, pc, profile, takes, take_check, take_measure,
                  int((overrides or {}).get("attempt") or 0), (overrides or {}).get("culprit_words"))
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
