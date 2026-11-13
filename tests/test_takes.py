"""Best-of-N takes (voice/takes.py + narrate): the pitch measure on synthetic audio, the selection rule, deterministic seeds,
the metrics cache, and the baseline staying one take. Fake engine only: no model is loaded."""
from __future__ import annotations

import numpy as np
import pytest

from test_narrate_long import FakeClone, SR, eng  # noqa: F401  (fixture)
from ullaslab_engine.audio import Wav
from ullaslab_engine.voice import narrate as N
from ullaslab_engine.voice import takes as T

TEXT = ("Copper stocks eased but a firmer case remains. That is what warehouses hold for buyers. "
        "It was six on the first and five on the eighth. Follow UllasLab. Education only.")


# ---------------------------------------------------------------- pitch measure on synthetic audio
def _tone(f_lo: float, f_hi: float, seconds: float = 2.0, sr: int = 16000, rate_hz: float = 1.2) -> np.ndarray:
    """Harmonic tone whose pitch sweeps sinusoidally between f_lo and f_hi (f_lo == f_hi: monotone)."""
    t = np.arange(int(seconds * sr)) / sr
    f0 = (f_lo + f_hi) / 2 + (f_hi - f_lo) / 2 * np.sin(2 * np.pi * rate_hz * t)
    ph = 2 * np.pi * np.cumsum(f0) / sr
    return (sum(np.sin(h * ph) / h for h in range(1, 6)) * 0.3).astype(np.float32)


def test_pitch_from_semitones_is_the_p10_p90_spread_without_octave_artefacts():
    st = np.linspace(-3, 3, 101)                      # a clean 6 st glide
    rng, art = T.pitch_from_semitones(st)
    assert rng == pytest.approx(4.8, abs=0.05) and art == 0.0
    with_jump = np.concatenate([st, [20.0, 20.0, st[0]]])   # an octave-jump artefact: dropped from the spread, counted as jumps
    rng2, art2 = T.pitch_from_semitones(with_jump)
    assert rng2 == pytest.approx(rng, abs=0.2) and art2 > 0
    assert T.pitch_from_semitones(np.array([1.0, 2.0])) == (0.0, 0.0)          # too little voiced audio


def test_pitch_metrics_ranks_a_wide_pitch_take_above_a_flat_one():
    pytest.importorskip("librosa")
    flat, narrow, wide = _tone(120, 120), _tone(115, 125), _tone(90, 190)
    r_flat, _ = T.pitch_metrics(flat, 16000)
    r_narrow, _ = T.pitch_metrics(narrow, 16000)
    r_wide, a_wide = T.pitch_metrics(wide, 16000)
    assert r_flat < 1.0 and r_flat < r_narrow < r_wide
    assert 6.0 < r_wide < 14.0                        # 90-190 Hz is 12.7 st end to end, p10-p90 a little less
    assert a_wide < 0.06                              # a smooth glide is not an artefact
    r_rs, _ = T.pitch_metrics(wide.astype(np.float32), 16000)   # resampling path: 24 kHz in
    r_24, _ = T.pitch_metrics(_tone(90, 190, sr=24000), 24000)
    assert r_24 == pytest.approx(r_rs, abs=1.5)


# ---------------------------------------------------------------- selection rule
def _t(seed, wer=0.0, dur=3.0, pitch=3.0, art=0.0):
    return T.Take(seed, wer, dur, pitch, art)


def test_selection_takes_the_widest_pitch_among_the_most_accurate():
    takes = [_t(0, wer=0, pitch=3.0), _t(10, wer=0, pitch=4.5), _t(20, wer=8, pitch=9.0), _t(30, wer=0, pitch=4.0)]
    assert T.select_take(takes, 0.06) == 1                 # the 9.0 take is the widest but mis-reads a word
    assert T.select_take([_t(0, wer=5, pitch=3), _t(10, wer=5, pitch=4)], 0.06) == 1     # all equally inaccurate: lowest WER ties
    assert T.select_take([_t(0, pitch=4.0), _t(10, pitch=4.0)], 0.06) == 0                # ties: the earliest take


def test_selection_rejects_wrong_length_and_artefact_takes_and_falls_back_to_lowest_wer():
    takes = [_t(0, dur=3.0, pitch=3), _t(10, dur=3.1, pitch=3.5), _t(20, dur=1.9, pitch=8), _t(30, dur=3.0, pitch=9, art=0.3)]
    assert T.select_take(takes, 0.06) == 1                 # 1.9 s is a truncated read, the 0.3 artefact share is a glitch
    allbad = [_t(0, wer=0, dur=1.0), _t(10, wer=0, dur=9.0), _t(20, wer=0, dur=5.0, art=0.9)]
    # nothing passes the length / artefact screen -> the first lowest-WER take
    assert T.select_take(allbad, 0.06) in (0, 1, 2)
    assert T.select_take([_t(0, wer=4, dur=1, art=0.9), _t(10, wer=2, dur=9, art=0.9), _t(20, wer=3, dur=5, art=0.9)], 0.06) == 1
    assert T.select_take([_t(0, pitch=2.0)], 0.06) == 0


def test_artefact_limit_scales_with_the_median_but_never_drops_below_the_floor():
    assert T.artefact_limit([_t(0, art=0.0)] * 4) == T.ARTEFACT_FLOOR
    assert T.artefact_limit([_t(0, art=0.1)] * 4) == pytest.approx(0.2)
    assert T.artefact_limit([]) == T.ARTEFACT_FLOOR


def test_take_seeds_stay_clear_of_the_retry_seeds():
    seeds = {T.TAKE_SEED_STEP * j for j in range(T.MAX_TAKES)}
    assert not seeds & {100, 200, 1000, 2000} and 1 not in seeds


# ---------------------------------------------------------------- narrate with a fake clone engine named chatterbox
class Meter:
    """Stands in for the ASR check and the pitch measure; the take is recognised by the call order per text."""
    def __init__(self, wer_for=None, pitch_for=None):
        self.checks: list[tuple[str, int]] = []
        self.wer_for, self.pitch_for = wer_for or (lambda text, k: 0.0), pitch_for or (lambda text, k: 3.0 + k)
        self.seen: dict[str, int] = {}

    def check(self, text, w, lang):
        k = self.seen.get(text, 0)
        self.seen[text] = k + 1
        self.checks.append((text, k))
        return self.wer_for(text, k)

    def measure(self, x, sr):
        # the measure runs right after check for the same take
        text, k = self.checks[-1]
        return self.pitch_for(text, k), 0.0


@pytest.fixture
def chat(eng):  # noqa: F811
    e = FakeClone(words_per_s=2.6)
    e.name = "chatterbox"
    base_eng = eng
    base_eng(e)
    from ullaslab_engine.tts import base
    base.register_engine("chatterbox", lambda: e)
    return e


def _run(chat, meter, takes, **kw):
    ov = {"delivery_profile": "baseline", "takes": takes, **kw.pop("overrides", {})}
    return N.narrate(TEXT, "en", engine="chatterbox", gate=False, normalize=False, overrides=ov,
                     take_check=meter.check, take_measure=meter.measure, **kw)


def test_n_takes_per_line_on_deterministic_seeds_and_the_widest_is_kept(chat):
    m = Meter(pitch_for=lambda text, k: [3.0, 4.0, 6.0, 5.0][k])
    w = _run(chat, m, 4)
    lines = len(N.plan_chunks(N.spoken_text(TEXT, "en", "western")))
    assert len(chat.calls) == 4 * lines
    seeds = sorted({s["seed"] for _, s in chat.calls})
    assert seeds == [0, 10, 20, 30]
    assert w.meta["takes"]["lines"] == lines and w.meta["takes"]["first_take_chosen"] == 0
    assert w.meta["takes"]["pitch_kept"] == 6.0 and w.meta["takes"]["pitch_all"] == pytest.approx(4.5)


def test_a_take_that_misreads_is_never_chosen_even_if_it_is_the_widest(chat):
    m = Meter(wer_for=lambda text, k: 12.0 if k == 2 else 0.0, pitch_for=lambda text, k: [3.0, 4.0, 9.0, 5.0][k])
    w = _run(chat, m, 4)
    assert w.meta["takes"]["pitch_kept"] == 5.0              # take 3, the widest among the accurate ones


def test_the_same_inputs_give_the_same_audio_and_selection(chat):
    m1, m2 = Meter(), Meter()
    a, b = _run(chat, m1, 3), _run(chat, m2, 3)
    assert a.meta["takes"] == b.meta["takes"] and abs(a.duration - b.duration) < 0.05


def test_cache_resumes_without_synthesising_or_checking_again(chat, tmp_path):
    m = Meter()
    _run(chat, m, 3, cache_dir=tmp_path)
    n_calls, n_checks = len(chat.calls), len(m.checks)
    m2 = Meter()
    _run(chat, m2, 3, cache_dir=tmp_path)
    assert len(chat.calls) == n_calls and m2.checks == [] and n_checks > 0


def test_one_take_is_the_old_path(chat):
    m = Meter()
    w = _run(chat, m, 1)
    assert m.checks == [] and "takes" not in w.meta
    lines = len(N.plan_chunks(N.spoken_text(TEXT, "en", "western")))
    assert len(chat.calls) == lines and all(s["seed"] == 0 for _, s in chat.calls)


def test_a_stock_voice_fallback_gets_one_take_and_no_asr(eng):  # noqa: F811
    e = FakeClone(words_per_s=2.6)
    eng(e)
    m = Meter()
    w = N.narrate(TEXT, "en", engine="fakeclone", gate=False, normalize=False,
                  overrides={"delivery_profile": "baseline", "takes": 4}, take_check=m.check, take_measure=m.measure)
    assert m.checks == [] and "takes" not in w.meta


def test_a_failing_later_take_is_skipped_not_fatal(chat):
    m = Meter()
    first = N.plan_chunks(N.spoken_text(TEXT, "en", "western"))[0].text
    seen = {"n": 0}
    real = chat.synth

    def flaky(text, lang, ref, settings=None):
        if text == first and settings and settings["seed"] == 10:
            from ullaslab_engine.tts.base import EngineUnavailable
            raise EngineUnavailable("chatterbox failed: IndexError")
        seen["n"] += 1
        return real(text, lang, ref, settings=settings)
    chat.synth = flaky
    w = _run(chat, m, 3)
    assert w.duration > 3 and w.meta["takes"]["lines"] >= 1


# ---------------------------------------------------------------- accuracy at the heard speed, reuse across WER retries
class SpeedMeter(Meter):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.lens: list[float] = []

    def check(self, text, w, lang):
        self.lens.append(len(w.samples) / w.sr)
        return super().check(text, w, lang)


def test_the_take_is_checked_at_the_speed_it_will_be_heard_at(chat):
    slow = FakeClone(words_per_s=1.8)          # reads slowly: the pacer will speed the read up, so the check must hear it sped up
    chat.words_per_s = 1.8
    m = SpeedMeter()
    w = _run(chat, m, 2, overrides={"pace": {"target_wpm": 150, "words": 20}})
    f = w.meta["takes"]["speed_est"]
    assert f > 1.02 and w.meta["pace"]["speedup"] > 1.02
    raw = [len(c.samples) / c.sr for c in [chat.synth(t, "en", None, {"seed": 0}) for t, _ in chat.calls[:1]]]
    assert min(m.lens) < raw[0] * 0.97          # heard faster than synthesised


def test_a_retry_reuses_every_take_and_check_and_adds_one_take_to_the_worst_lines_only(chat, tmp_path):
    lines = [c.text for c in N.plan_chunks(N.spoken_text(TEXT, "en", "western"))]
    bad = lines[1]
    m = Meter(wer_for=lambda text, k: 8.0 if text == bad else 0.0)          # no take of line 1 reads right
    ov = {"take_seed": 0, "attempt": 0}
    _run(chat, m, 2, cache_dir=tmp_path, overrides=ov)
    s0, c0 = len(chat.calls), len(m.checks)
    assert s0 == 2 * len(lines) and c0 == 2 * len(lines)
    m2 = Meter(wer_for=lambda text, k: 8.0 if text == bad else 0.0)
    w = _run(chat, m2, 2, cache_dir=tmp_path, overrides={"take_seed": 0, "attempt": 1})
    assert len(chat.calls) - s0 == 1 and [t for t, _ in chat.calls[s0:]] == [bad]       # one new take, for the bad line only
    assert [t for t, _ in m2.checks] == [bad]                                           # only the new take is transcribed
    assert {s["seed"] for t, s in chat.calls if t == bad} == {0, 10, 20}
    assert w.meta["takes"]["asr_calls"] == 2 * len(lines) + 1


def test_a_retry_without_a_culprit_line_still_adds_takes_to_the_fastest_lines_and_never_more_than_the_cap(chat, tmp_path):
    m = Meter()
    _run(chat, m, 2, cache_dir=tmp_path, overrides={"take_seed": 0, "attempt": 0})
    s0 = len(chat.calls)
    _run(chat, Meter(), 2, cache_dir=tmp_path, overrides={"take_seed": 0, "attempt": 2})
    added = len(chat.calls) - s0
    assert 0 < added <= N.MAX_EXTRA_LINES * 2


def test_first_attempt_adds_no_extra_takes(chat, tmp_path):
    m = Meter(wer_for=lambda text, k: 5.0)
    _run(chat, m, 2, cache_dir=tmp_path, overrides={"take_seed": 0, "attempt": 0})
    lines = len(N.plan_chunks(N.spoken_text(TEXT, "en", "western")))
    assert len(chat.calls) == 2 * lines


def test_a_check_at_another_speed_is_a_new_record_and_the_same_speed_is_cached(chat, tmp_path):
    m = Meter()
    _run(chat, m, 2, cache_dir=tmp_path, overrides={"take_seed": 0})
    n = len(m.checks)
    _run(chat, Meter(), 2, cache_dir=tmp_path, overrides={"take_seed": 0})
    assert n == 2 * len(N.plan_chunks(N.spoken_text(TEXT, "en", "western")))
    m3 = Meter()
    _run(chat, m3, 2, cache_dir=tmp_path, overrides={"take_seed": 0, "pace": {"target_wpm": 90, "words": 20}})   # other speed: re-checked
    assert len(m3.checks) > 0


def test_retry_swaps_in_a_new_take_for_the_line_that_holds_a_misheard_word(chat, tmp_path):
    lines = [c.text for c in N.plan_chunks(N.spoken_text(TEXT, "en", "western"))]
    word = lines[2].split()[0].strip(".,").lower()
    ov0 = {"take_seed": 0, "attempt": 0}
    w0 = _run(chat, Meter(pitch_for=lambda t, k: 5.0 if k == 0 else 3.0), 2, cache_dir=tmp_path, overrides=ov0)
    n0 = len(chat.calls)
    m = Meter(pitch_for=lambda t, k: 5.0 if k == 0 else 3.0)
    w1 = _run(chat, m, 2, cache_dir=tmp_path, overrides={"take_seed": 0, "attempt": 1, "culprit_words": [word]})
    new = chat.calls[n0:]
    assert new and all(any(word == x.strip(".,").lower() for x in t.split()) for t, _ in new) and len(new) <= 4
    assert all(s["seed"] == 20 for _, s in new)                     # take index 2 = seed 20, the first take beyond N
    assert w1.meta["takes"]["asr_calls"] == w0.meta["takes"]["asr_calls"] + len(new)
    assert w1.meta["takes"]["first_take_chosen"] < w0.meta["takes"]["first_take_chosen"]     # a first (liveliest) take was swapped out


def test_voice_phase_hands_the_misheard_words_to_the_next_attempt_privately(tmp_path):
    import json
    from test_actions import _Phase
    from ullaslab_engine.studio import actions as AC
    seen = []
    p = _Phase(tmp_path, [3.5, 1.0])
    base_narrate = p.narrate

    def narrate(text, lang, ref, cache_dir=None, overrides=None):
        seen.append(dict(overrides or {}))
        return base_narrate(text, lang, ref, cache_dir=cache_dir, overrides=overrides)
    p.narrate = narrate
    # the hypothesis drops/replaces words, so the real wer_diff has substitutions to report
    p.words = [(w + "x" if i % 9 == 4 else w, a, b) for i, (w, a, b) in enumerate(p.words)]
    res, lines = p.run()
    assert (p.w / AC.CULPRITS).is_file()
    assert "culprit_words" not in seen[0] and seen[0]["attempt"] == 0 and seen[1]["attempt"] == 1
    assert seen[1]["take_seed"] == seen[0]["take_seed"]
    assert isinstance(seen[1].get("culprit_words"), list)
    assert not any("culprit" in json.dumps(res) for _ in [0]) and AC.CULPRITS not in json.dumps(res)   # not in the gate result
