"""Per-line delivery (voice/delivery.py + config/delivery.yaml): tag vocabulary, marker handling, the tag-to-settings mapping,
the unchanged baseline, and the voice gates left exactly as they were. Fake engine only: no model is loaded."""
from __future__ import annotations

import json

import numpy as np
import pytest
import yaml

from conftest import speechlike
from test_narrate_long import FakeClone, SR, eng  # noqa: F401  (fixture)
from ullaslab_engine.config import CONFIG_DIR, quality
from ullaslab_engine.studio import actions as AC
from ullaslab_engine.voice import delivery as D
from ullaslab_engine.voice import narrate as N
from ullaslab_engine.voice.prosody import strip_markers

TEXT = ("Copper stocks eased but a firmer case remains. That is what warehouses hold for buyers. "
        "It was 6.20 on the first and 6.05 on the eighth. Firmer weakens if it holds below the 6.05 level. Follow UllasLab.")
TAGGED = ("[[d:hook]] Copper stocks eased but a firmer case remains. [[d:explain]] That is what warehouses hold for buyers. "
          "[[d:reveal]] It was 6.20 on the first and 6.05 on the eighth. [[d:caution]] Firmer weakens if it holds below the 6.05 level. "
          "[[d:signoff]] Follow UllasLab.")


# ---------------------------------------------------------------- vocabulary, markers, profiles
def test_vocabulary_is_fixed_and_the_yaml_agrees():
    assert D.TAGS == ("hook", "tension", "reveal", "explain", "caution", "signoff")
    assert tuple(yaml.safe_load((CONFIG_DIR / "delivery.yaml").read_text())["tags"]) == D.TAGS
    assert D.profile_names() == ["baseline", "mild", "strong", "tuned"]


def test_every_shipped_profile_loads_inside_its_bounds():
    for name in D.profile_names():
        prof = D.load_profile(name)
        assert set(prof) <= set(D.TAGS)
        for st in prof.values():
            for k, v in st.items():
                lo, hi = D.BOUNDS[k]
                assert lo <= v <= hi


def test_baseline_profile_is_empty_and_default_is_baseline():
    assert D.load_profile("baseline") == {}
    assert D.default_profile("en") == "baseline"
    assert D.default_profile() == "baseline"


def test_profile_validation_rejects_bad_names_tags_fields_and_values(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="unknown delivery profile"):
        D.load_profile("wild")
    from ullaslab_engine import config as C
    for bad, msg in [({"p": {"shout": {}}}, "unknown tag"), ({"p": {"hook": {"volume": 1}}}, "unknown field"),
                     ({"p": {"hook": {"exaggeration": 1.5}}}, "outside"), ({"p": {"hook": {"pause_after": 2.0}}}, "outside"),
                     ({"p": {"hook": {"tempo": 1.4}}}, "outside"), ({"p": {"hook": {"exaggeration": True}}}, "outside")]:
        monkeypatch.setattr(D, "_load", lambda name, bad=bad: {"profiles": bad})
        with pytest.raises(ValueError, match=msg):
            D.load_profile("p")


def test_take_delivery_sets_sticky_and_never_cuts_a_sentence():
    assert D.take_delivery("[[d:hook]] Hello there.") == ("Hello there.", "hook", "hook")
    assert D.take_delivery("Plain.", None) == ("Plain.", None, None)
    assert D.take_delivery("Plain.", "reveal") == ("Plain.", "reveal", "reveal")           # sticky
    assert D.take_delivery("[[d:neutral]] Plain.", "reveal") == ("Plain.", None, None)
    # a scene boundary inside a sentence: this sentence keeps its tag, the NEXT one gets the new one
    assert D.take_delivery("It sits above the two year, [[d:explain]] and bounced.", "tension") == (
        "It sits above the two year, and bounced.", "tension", "explain")
    assert D.take_delivery("[[d:bogus]] Text.", "hook")[2] == "hook"                      # unknown tag ignored


def test_markers_are_stripped_from_the_word_count_the_gate_uses():
    assert strip_markers(TAGGED).split() == strip_markers(TEXT).split()
    assert AC.gate_words(TAGGED) == AC.gate_words(TEXT)


# ---------------------------------------------------------------- chunk plan
def test_plan_chunks_carries_tags_and_without_markers_is_identical():
    plain = N.plan_chunks(TEXT)
    assert [c.delivery for c in plain] == [None] * len(plain)
    tagged = N.plan_chunks(TAGGED)
    assert [(c.text, c.pause, c.keep) for c in tagged] == [(c.text, c.pause, c.keep) for c in plain]
    assert [c.delivery for c in tagged] == ["hook", "explain", "reveal", "caution", "signoff"]


def test_a_decimal_before_a_scene_boundary_does_not_swallow_the_next_tag():
    plan = N.plan_chunks("[[d:caution]] Firmer weakens if it holds below 6.05. [[d:signoff]] Follow UllasLab.")
    assert [c.delivery for c in plan] == ["caution", "signoff"]
    # without a marker the old behaviour stands: "6.05. Follow" is read as one piece
    assert len(N.plan_chunks("Firmer weakens if it holds below 6.05. Follow UllasLab.")) == 1


def test_short_chunk_merge_keeps_the_first_tag():
    plan = N.plan_chunks("[[d:tension]] Oil rose. [[d:reveal]] Then it fell back sharply today.")
    assert len(plan) == 1 and plan[0].delivery == "tension" and "[[" not in plan[0].text


# ---------------------------------------------------------------- tag -> settings
def _calls(eng, text, profile=None, **kw):
    e = FakeClone(words_per_s=2.6)
    eng(e)
    ov = {"delivery_profile": profile} if profile else None
    N.narrate(text, "en", engine="fakeclone", gate=False, normalize=False, overrides=ov, **kw)
    return e.calls


def test_baseline_ignores_tags_and_matches_untagged_synthesis_exactly(eng):
    a = _calls(eng, TEXT)
    b = _calls(eng, TAGGED)                          # profile baseline (the config default): tags are inert
    c = _calls(eng, TAGGED, "baseline")
    assert a == b == c
    assert all("temp_factor" not in s for _, s in a)


def test_untagged_text_is_unchanged_under_every_profile(eng):
    base = _calls(eng, TEXT)
    for name in ("mild", "strong", "tuned"):
        got = _calls(eng, TEXT, name)
        assert [(t, {k: v for k, v in s.items() if k != "temp_factor"}) for t, s in got] == base


@pytest.mark.parametrize("name", ["mild", "strong", "tuned"])
def test_each_tag_maps_to_its_profile_settings(eng, name):
    prof = D.load_profile(name)
    calls = _calls(eng, TAGGED, name)
    tags = ["hook", "explain", "reveal", "caution", "signoff"]
    assert len(calls) == 5
    glob = N.voice_settings("en")
    for (text, st), tag in zip(calls, tags):
        want = prof.get(tag, {})
        assert st["exaggeration"] == pytest.approx(want.get("exaggeration", glob["exaggeration"]))
        assert st["effective_cfg_weight"] == pytest.approx(want.get("cfg_weight", glob["effective_cfg_weight"]))
        assert st["temperature"] == pytest.approx(want.get("temperature", glob["temperature"]))


def test_strong_is_more_expressive_than_mild_on_hook_and_reveal():
    m, s = D.load_profile("mild"), D.load_profile("strong")
    for tag in ("hook", "reveal"):
        assert s[tag]["exaggeration"] > m[tag]["exaggeration"] > 0.4
        assert s[tag]["cfg_weight"] < m[tag]["cfg_weight"]


def test_non_english_native_accent_keeps_cfg_zero():
    assert D.synth_overrides("hook", D.load_profile("strong"), cfg_forced=True) == {"exaggeration": 0.7, "temperature": 0.8}
    assert D.synth_overrides(None, D.load_profile("strong")) == {}
    assert D.synth_overrides("explain", D.load_profile("mild")) == {}


def test_naturalness_retry_keeps_its_cooler_temperature_on_tagged_lines():
    st = {"temperature": 0.7 * 0.85, "temp_factor": 0.85, "accent": "mine", "exaggeration": 0.4, "effective_cfg_weight": 0.5}
    out = N._chunk_settings(st, "hook", D.load_profile("strong"), "en")
    assert out["temperature"] == pytest.approx(0.8 * 0.85)
    assert N._chunk_settings(st, None, D.load_profile("strong"), "en") is st


def test_chunk_cache_key_differs_between_profiles(eng, tmp_path):
    e = FakeClone(words_per_s=2.6); eng(e)
    N.narrate(TAGGED, "en", engine="fakeclone", gate=False, normalize=False, cache_dir=tmp_path, overrides={"delivery_profile": "mild"})
    n1 = len(e.calls)
    N.narrate(TAGGED, "en", engine="fakeclone", gate=False, normalize=False, cache_dir=tmp_path, overrides={"delivery_profile": "strong"})
    assert len(e.calls) > n1                          # different settings: not served from mild's cache
    n2 = len(e.calls)
    N.narrate(TAGGED, "en", engine="fakeclone", gate=False, normalize=False, cache_dir=tmp_path, overrides={"delivery_profile": "strong"})
    assert len(e.calls) == n2                         # same profile: fully cached


# ---------------------------------------------------------------- pauses, tempo, gain
def test_apply_delivery_pauses_tempo_and_gain():
    sr = SR
    parts = [np.full(sr, 0.1, np.float32) for _ in range(3)]
    prof = {"reveal": {"pause_before": 0.3, "tempo": 0.96, "gain_db": 1.0}, "hook": {"pause_after": 0.3}}
    p, pa, k, used = N.apply_delivery(parts, [0.1, 0.1, 0.0], [False] * 3, ["hook", "explain", "reveal"], prof, sr)
    assert pa == [0.3, 0.3, 0.0] and k == [True, True, False]      # hook after + reveal before land on the same gap
    assert used == {"hook": 1, "reveal": 1}
    assert len(p[2]) > sr and p[0] is parts[0]                     # reveal slowed down; hook untouched
    assert np.abs(p[2]).max() > 0.1 * 1.05 * 0.9                   # +1 dB


def test_last_line_gets_no_pause_after_and_first_none_before():
    parts = [np.zeros(100, np.float32)] * 2
    _, pa, _, _ = N.apply_delivery(parts, [0.2, 0.0], [False, False], ["signoff", "signoff"],
                                   {"signoff": {"pause_before": 0.3, "pause_after": 0.3}}, 24000)
    assert pa == [0.3, 0.0]


def test_tuned_profile_wpm_still_lands_in_the_gate_range(eng):
    e = FakeClone(words_per_s=3.2); eng(e)
    w = N.narrate(TAGGED, "en", engine="fakeclone", gate=False, normalize=False,
                  overrides={"delivery_profile": "tuned", "pace": {"target_wpm": 150, "words": AC.gate_words(TAGGED)}})
    q = quality()["A3_narration"]
    assert q["wpm_min"] <= w.meta["pace"]["wpm"] <= q["wpm_max"]
    assert w.meta["delivery"] == {"hook": 1, "reveal": 1, "caution": 1, "signoff": 1}      # explain is a baseline entry


# ---------------------------------------------------------------- scenes -> text
def _out(*pairs):
    return {"output": "short", "scenes": [{"id": f"s{i:02d}", "narration": ({"text": t, **({"delivery": d} if d else {})})}
                                          for i, (t, d) in enumerate(pairs, 1)]}


def test_output_text_unchanged_when_no_scene_has_a_tag():
    o = _out(("One. Two words.", None), ("Three here.", None))
    assert AC.output_text(o) == "One. Two words. Three here."


def test_output_text_marks_tagged_scenes_and_resets_untagged_ones():
    o = _out(("Hook line here.", "hook"), ("Plain middle.", None), ("[[pause:0.8]] The number.", "reveal"))
    assert AC.output_text(o) == "[[d:hook]] Hook line here. [[d:neutral]] Plain middle. [[pause:0.8]] [[d:reveal]] The number."
    plan = N.plan_chunks(AC.output_text(o))
    assert [c.delivery for c in plan] == ["hook", None, "reveal"]


def test_output_text_rejects_an_unknown_tag():
    with pytest.raises(AC.ActionsError, match="narration.delivery"):
        AC.output_text(_out(("Hook line here.", "shouting")))


# ---------------------------------------------------------------- gates untouched
def test_voice_gate_limits_and_retry_rule_are_unchanged():
    a3 = quality()["A3_narration"]
    assert (a3["max_wer_pct"], a3["wpm_min"], a3["wpm_max"], a3["max_silence_s"]) == (3, 135, 175, 1.2)
    assert (AC.MAX_VOICE_ATTEMPTS, AC.SEED_STEP, AC.WER_ONLY) == (3, 1000, {("A3", "wer_pct")})
    assert N.CHUNK_RETRIES == 3


def test_every_delivery_pause_stays_well_under_the_silence_limit():
    limit = quality()["A3_narration"]["max_silence_s"]
    for name in D.profile_names():
        for st in D.load_profile(name).values():
            assert st.get("pause_before", 0) + st.get("pause_after", 0) + 0.55 < limit


def test_config_default_is_baseline_in_languages_yaml():
    assert yaml.safe_load((CONFIG_DIR / "languages.yaml").read_text())["voice_defaults"]["delivery_profile"] == "baseline"
