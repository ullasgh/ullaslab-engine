"""Long narration (M2b): chunking, per-chunk retry, crash-safe chunk cache, clean joins, pace target, markup.
All with a fake engine; no model is loaded and no real synthesis runs."""
from __future__ import annotations

import numpy as np
import pytest

from conftest import speechlike
from ullaslab_engine.audio import Wav
from ullaslab_engine.tts import base
from ullaslab_engine.tts.base import EngineUnavailable, NoVoiceAvailable
from ullaslab_engine.voice import narrate as N
from ullaslab_engine.voice import naturalness
from ullaslab_engine.voice.prosody import split_marked, strip_markers

SR = 24000
LONG = ("Oil prices jumped this spring. One. Shipping through the strait fell sharply, and insurers raised their rates. "
        "Why does that matter for you? Because fuel costs feed into almost everything you buy.\n\n"
        "Some analysts expected a quick recovery. Others did not. Here is what the data shows. "
        "Traffic stayed low for months while prices stayed high. Follow UllasLab.")


class FakeClone:
    """Stands in for the clone engine: like Chatterbox it fails on very short text; leading/trailing model silence and a
    level that varies per call, so joins and loudness matter. `fail` maps text -> how many times to fail first."""
    name = "fakeclone"; clones_voice = False; uses_settings = True

    def __init__(self, words_per_s=2.4, fail=None, crash_after=None, lead_s=0.35, tail_s=0.5, levels=(0.1, 0.35)):
        self.calls: list[tuple[str, dict]] = []
        self.wps, self.fail, self.crash_after = words_per_s, dict(fail or {}), crash_after
        self.lead_s, self.tail_s, self.levels = lead_s, tail_s, levels

    def supports(self, lang):
        return True

    def synth(self, text, lang, ref, settings=None):
        self.calls.append((text, dict(settings or {})))
        if self.crash_after is not None and len(self.calls) > self.crash_after:
            raise RuntimeError("process died")            # not an engine error: the whole call is lost (pre-M2b behaviour)
        if len(text.split()) < 2:
            raise EngineUnavailable("chatterbox failed: IndexError")
        if self.fail.get(text, 0) > 0:
            self.fail[text] -= 1
            raise EngineUnavailable("chatterbox failed: IndexError")
        n = len(self.calls)
        lvl = self.levels[n % len(self.levels)]
        body = speechlike(max(0.6, len(text.split()) / self.wps), SR, seed=n, level=lvl).samples
        x = np.concatenate([np.zeros(int(self.lead_s * SR), np.float32), body, np.zeros(int(self.tail_s * SR), np.float32)])
        return Wav(x.astype(np.float32), SR)


@pytest.fixture
def eng(monkeypatch):
    monkeypatch.delenv("ULLASLAB_TTS_FORCE", raising=False)
    monkeypatch.delenv("ULLASLAB_TTS_CACHE", raising=False)
    holder = {}

    def use(e):
        holder["e"] = e
        base._CACHE.pop("fakeclone", None)
        base.register_engine("fakeclone", lambda: holder["e"])
        return e
    yield use
    base._FACTORIES.clear()
    base._CACHE.clear()


# ---------------------------------------------------------------- chunk plan
def test_one_word_sentences_are_merged_unless_a_marker_holds_the_pause():
    plan = N.plan_chunks("Oil rose sharply. One. Then it fell back.")
    assert [c.text for c in plan] == ["Oil rose sharply.", "One. Then it fell back."]
    plan = N.plan_chunks("Oil rose sharply. [[hook]] One. [[pause:0.8]] Then it fell back.")
    assert [c.text for c in plan] == ["Oil rose sharply.", "One.", "Then it fell back."]
    assert plan[1].pause == 0.8 and plan[1].keep
    assert [c.text for c in N.plan_chunks("It fell back again. Done.")] == ["It fell back again. Done."]   # trailing short one


def test_markup_pause_and_emphasis():
    out = split_marked("Prices rose [[pause:0.9]] then fell. A *big* move.")
    assert out[0] == ("Prices rose", 0.9, True)
    assert strip_markers("A *big* move [[pause]] here [[hook]] now.") == "A big move here now."
    assert strip_markers("2*3*4 and a*b stay") == "2*3*4 and a*b stay"
    assert split_marked("Wait. [[pause:9]] Go.")[0][1] == 2.0                  # capped


# ---------------------------------------------------------------- the crash
def test_long_text_with_a_one_word_sentence_no_longer_crashes(eng):
    e = eng(FakeClone())
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False)
    assert w.duration > 20 and w.engine == "fakeclone"
    assert all(len(t.split()) >= 2 for t, _ in e.calls)


def test_transient_chunk_failure_is_retried_with_new_seeds(eng):
    e = eng(FakeClone(fail={"Here is what the data shows.": 2}))
    N.narrate(LONG, "en", engine="fakeclone", gate=False)
    tries = [s["seed"] for t, s in e.calls if t == "Here is what the data shows."]
    assert tries == [0, 100, 200]


def test_persistent_failure_merges_into_next_then_raises_naming_the_chunk(eng):
    e = eng(FakeClone(fail={"Some analysts expected a quick recovery.": 99}))
    N.narrate(LONG, "en", engine="fakeclone", gate=False)
    assert any(t.startswith("Some analysts expected a quick recovery. Others did not.") for t, _ in e.calls)
    eng(FakeClone(fail={"Follow Ullas Lab.": 99}))      # the last chunk has no next one to join
    with pytest.raises(NoVoiceAvailable, match="Follow Ullas Lab"):     # (the lexicon speaks the brand as two words)
        N.narrate(LONG, "en", engine="fakeclone", gate=False)


def test_chunk_cache_resumes_after_a_crash_without_redoing_finished_chunks(eng, tmp_path):
    cache = tmp_path / "tts_cache"
    e = eng(FakeClone(crash_after=4))
    with pytest.raises(RuntimeError, match="process died"):
        N.narrate(LONG, "en", engine="fakeclone", gate=False, cache_dir=cache)
    assert len(list(cache.glob("*.wav"))) == 4 and not list(cache.glob("*.part.wav"))
    e2 = eng(FakeClone())
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False, cache_dir=cache)
    total = w.meta["chunks"]
    assert len(e2.calls) == total - 4                      # only the chunks the crash lost
    e3 = eng(FakeClone())
    w2 = N.narrate(LONG, "en", engine="fakeclone", gate=False, cache_dir=cache)
    assert e3.calls == [] and np.array_equal(w.samples, w2.samples)   # a full rerun is free and identical


def test_chunk_key_covers_text_voice_and_settings(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"voice-a")
    s = {"exaggeration": 0.4, "temperature": 0.7, "effective_cfg_weight": 0.5, "accent": "native", "ref_clip": 1, "speaker": 0, "seed": 0}
    k = N.chunk_key("Hello there friend.", "en", "chatterbox", s, N._ref_sha(ref))
    assert k == N.chunk_key("Hello there friend.", "en", "chatterbox", dict(s), N._ref_sha(ref))
    assert k != N.chunk_key("Hello there friends.", "en", "chatterbox", s, N._ref_sha(ref))
    assert k != N.chunk_key("Hello there friend.", "hi", "chatterbox", s, N._ref_sha(ref))
    assert k != N.chunk_key("Hello there friend.", "en", "kokoro", s, N._ref_sha(ref))
    for key in ("temperature", "seed", "exaggeration", "ref_clip"):
        assert k != N.chunk_key("Hello there friend.", "en", "chatterbox", {**s, key: 9}, N._ref_sha(ref)), key
    ref.write_bytes(b"voice-b")                              # a swapped reference voice never reuses old audio
    assert k != N.chunk_key("Hello there friend.", "en", "chatterbox", s, N._ref_sha(ref))


def test_damaged_cache_entry_is_resynthesised(eng, tmp_path):
    cache = tmp_path / "c"
    eng(FakeClone())
    N.narrate("Oil prices jumped this spring. Shipping fell sharply.", "en", engine="fakeclone", gate=False, cache_dir=cache)
    victim = sorted(cache.glob("*.json"))[0]
    victim.write_text('{"engine": "fakeclone", "samples": 3, "sr": 24000}')
    e = eng(FakeClone())
    N.narrate("Oil prices jumped this spring. Shipping fell sharply.", "en", engine="fakeclone", gate=False, cache_dir=cache)
    assert len(e.calls) == 1


# ---------------------------------------------------------------- joins and loudness
def test_joins_trim_model_silence_and_match_levels(eng):
    eng(FakeClone(lead_s=0.6, tail_s=0.9, levels=(0.05, 0.4)))
    w = N.narrate("Oil prices jumped this spring. Shipping fell sharply in March. Insurers raised their rates again.", "en",
                  engine="fakeclone", gate=False, normalize=False, pace=False)
    from ullaslab_engine.audio import max_silence_s
    assert max_silence_s(w) < 0.42 + 0.2                # the pause, not pause + 1.5 s of model silence
    m = naturalness.metrics(w)
    assert m["pause_max_s"] <= 1.2
    chunks = [speechlike(2.0, SR, seed=i, level=l).samples for i, l in enumerate((0.12, 0.3, 0.2))]
    lv = [N._active_db(c, SR) for c in N.level_match(chunks, SR)]
    assert max(lv) - min(lv) < 1.0
    far = N.level_match([chunks[0] * 0.01, chunks[1]], SR)   # never more than MAX_LEVEL_DB of correction
    assert abs((N._active_db(far[1], SR) - N._active_db(chunks[1], SR))) <= N.MAX_LEVEL_DB + 0.1


def test_edges_are_faded_no_click():
    x = np.ones(SR, np.float32) * 0.5
    y = N._trim(x, SR)
    assert abs(y[0]) < 1e-6 and abs(y[-1]) < 1e-6


# ---------------------------------------------------------------- pace
def _f0_median(w: Wav) -> float:
    f0 = naturalness.f0_track(w.samples.astype(np.float64), w.sr)
    return float(np.nanmedian(f0))


def test_slow_engine_is_brought_to_the_target_pace_without_changing_pitch(eng):
    eng(FakeClone(words_per_s=2.5))                   # 150 wpm of speech, about 125 once pauses are added
    raw = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False, pace=False)
    eng(FakeClone(words_per_s=2.5))
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False)
    p = w.meta["pace"]
    assert p["raw_wpm"] < 130 and p["wpm"] >= 0.97 * 150 and p["speedup"] <= 1.15 and 0.6 <= p["pause_scale"] <= 1.0
    assert w.duration < raw.duration * 0.92
    assert abs(_f0_median(w) / _f0_median(raw) - 1) < 0.04       # same voice: pitch kept
    assert not any(f.startswith("pace:") for f in w.flags)


def test_pace_is_bounded_and_flags_a_script_that_is_too_slow(eng):
    eng(FakeClone(words_per_s=1.2))
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False)
    assert w.meta["pace"]["speedup"] == 1.15
    assert any(f.startswith("pace:") for f in w.flags)
    eng(FakeClone(words_per_s=5.0))                     # far too fast (about 220 wpm): slowed as far as allowed, flagged
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False)
    assert w.meta["pace"]["speedup"] == round(1 / 1.15, 3) and w.meta["pace"]["pause_scale"] == 1.3
    assert any(f.startswith("pace:") and "over" in f for f in w.flags)


def test_fast_engine_is_slowed_into_the_a3_range_without_changing_pitch(eng):
    """WP8 regression: Chatterbox read the Actions fixture at 172-183 wpm (A3 allows 135-175) and the pacer only ever sped
    speech up. A read about 20% too fast must come back to the target with the pitch kept."""
    from ullaslab_engine.config import quality
    q = quality()["A3_narration"]
    eng(FakeClone(words_per_s=3.8))                     # about 180 wpm once pauses are added (the runner read 172-183)
    raw = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False, pace=False)
    eng(FakeClone(words_per_s=3.8))
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False, normalize=False)
    p = w.meta["pace"]
    assert p["raw_wpm"] > q["wpm_max"] and q["wpm_min"] <= p["wpm"] <= 160
    assert p["speedup"] < 1.0 and w.duration > raw.duration * 1.1
    from ullaslab_engine.audio import max_silence_s
    assert max_silence_s(w) <= q["max_silence_s"]                # longer pauses stay under the A3 silence limit
    assert abs(_f0_median(w) / _f0_median(raw) - 1) < 0.04       # same voice: pitch kept
    assert not any(f.startswith("pace:") for f in w.flags)


def test_explicit_pauses_are_kept_when_pacing(eng):
    eng(FakeClone(words_per_s=2.0))
    plan_text = "Oil prices jumped this spring. [[hook]] Shipping fell sharply in March. Insurers raised their rates again."
    chunks = [np.ones(SR * 2, np.float32) * 0.1] * 3
    _, pauses, info = N.fit_pace(chunks, [0.65, 0.42, 0.0], [True, False, False], 16, SR, N.pace_settings("en"))
    assert pauses[0] == 0.65 and pauses[1] < 0.42
    assert N.plan_chunks(plan_text)[0].keep


def test_pace_target_is_configurable(eng):
    p = N.pace_settings("en", {"pace": {"target_wpm": 120, "max_speedup": 1.05}})
    assert p["target_wpm"] == 120 and p["max_speedup"] == 1.05
    assert N.pace_settings("en")["target_wpm"] == 150


def test_paced_result_passes_the_naturalness_checks(eng):
    eng(FakeClone(words_per_s=2.2))
    w = N.narrate(LONG, "en", engine="fakeclone", gate=False)
    rep = naturalness.score(w)
    assert rep.metrics["pause_max_s"] <= 1.2
    assert not [f for f in rep.failures if f.startswith(("pause_max_s", "pause_ratio"))]


# ---------------------------------------------------------------- lexicon on every path
def test_lexicon_and_markup_reach_the_engine_on_every_path(eng):
    e = eng(FakeClone())
    N.narrate("The *WTI* price rose. [[pause]] P&L was flat today.", "en", engine="fakeclone", gate=False)
    said = " ".join(t for t, _ in e.calls)
    assert "W T I" in said and "P and L" in said and "*" not in said and "[[" not in said
    from ullaslab_engine import pipeline as P
    seen = []
    P._raw_tts, keep = (lambda text, lang, ref=None, **kw: seen.append(text) or Wav(np.zeros(100, np.float32), SR)), P._raw_tts
    try:
        P.default_tts("The *WTI* price rose. [[pause]] P&L was flat.", "en")
    finally:
        P._raw_tts = keep
    assert seen == ["The W T I price rose. P and L was flat."]


def test_voice_narrate_cli_resumes_from_its_chunk_cache(eng, tmp_path, capsys):
    from ullaslab_engine.cli import main
    (tmp_path / "script.txt").write_text(LONG)
    e = eng(FakeClone())
    assert main(["voice-narrate", "--text", str(tmp_path / "script.txt"), "--out", str(tmp_path / "voice.wav"), "--engine", "fakeclone"]) == 0
    assert (tmp_path / "voice.wav").is_file() and any((tmp_path / "work" / "tts_cache").glob("*.wav"))
    n = len(e.calls)
    e2 = eng(FakeClone())
    assert main(["voice-narrate", "--text", str(tmp_path / "script.txt"), "--out", str(tmp_path / "voice2.wav"), "--engine", "fakeclone",
                 "--cache-dir", str(tmp_path / "work" / "tts_cache")]) == 0
    assert n > 0 and e2.calls == []
    assert '"pace"' in capsys.readouterr().out


def test_pause_marker_survives_number_verbalisation_end_to_end(eng):
    e = eng(FakeClone())
    w = N.narrate("Rates rose 3.2% this year. [[pause:0.8]] Then they fell back again.", "en", engine="fakeclone", gate=False,
                  normalize=False, pace=False)
    said = [t for t, _ in e.calls]
    assert said == ["Rates rose three point two percent this year.", "Then they fell back again."]
    assert not any("pause" in t or "[[" in t for t in said)
    from ullaslab_engine.audio import max_silence_s
    assert 0.75 <= max_silence_s(w) <= 0.95                 # the 0.8 s marker pause, not the 0.42 s full stop
    assert N.spoken_text("Up 5% [[pause:1.5]] down *2%*", "en") == "Up five percent [[pause:1.5]] down two percent"


def test_short_sentence_at_a_paragraph_end_keeps_the_paragraph_break():
    plan = N.plan_chunks("Oil prices jumped this spring. Briefly.\n\nThen shipping fell sharply in March.")
    assert [c.text for c in plan] == ["Oil prices jumped this spring. Briefly.", "Then shipping fell sharply in March."]
    assert plan[0].pause == pytest.approx(0.8)


def test_slow_down_never_stretches_an_inner_pause_past_the_cap():
    """WP8: after slowing Chatterbox down, a mid-chunk pause of the engine's own grew to 1.2 s (A3 max_silence_s limit)."""
    from ullaslab_engine.audio import max_silence_s, Wav
    tone = (0.2 * np.sin(2 * np.pi * 220 * np.arange(SR) / SR)).astype(np.float32)
    x = np.concatenate([tone, np.zeros(int(SR * 1.1), np.float32), tone])
    y = N.cap_inner_silence(N.atempo(x, SR, 1 / 1.15), SR)
    assert max_silence_s(Wav(y, SR)) <= N.PAUSE_CAP_S + 0.04
    assert len(y) > 2 * SR                                         # the speech itself is kept
