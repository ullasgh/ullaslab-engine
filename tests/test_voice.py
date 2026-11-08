"""WP11 voice layer tests. Fixtures are synthetic tones/noise only: no real voice data anywhere."""
import json
import numpy as np
import pytest
import soundfile as sf
from conftest import speechlike
from ullaslab_engine.audio import Wav
from ullaslab_engine.voice import demo, naturalness, post, prepare, prosody, settings, textnorm
from ullaslab_engine.voice.narrate import narrate, resolve_ref
from ullaslab_engine.tts import base


# ---------- settings ----------
def test_native_accent_zeroes_cfg_for_non_english_only():
    assert settings.voice_settings("hi")["effective_cfg_weight"] == 0.0
    assert settings.voice_settings("en")["effective_cfg_weight"] == 0.5
    assert settings.voice_settings("hi", {"accent": "mine"})["effective_cfg_weight"] == 0.5


def test_defaults_and_indic_speakers():
    assert settings.voice_settings("es")["ref_clip"] == 1
    assert settings.voice_settings("ta")["speakers"] == ["Jaya", "Kavitha"]
    with pytest.raises(ValueError):
        settings.voice_settings("es", {"accent": "loud"})
    with pytest.raises(ValueError):
        settings.voice_settings("es", {"ref_clip": 4})


def test_apply_choices_validation():
    ok = settings.apply_choices({"hi": {"accent": "mine", "ref_clip": 2}, "ta": {"speaker": 1}})
    assert ok["ta"]["speaker"] == 1
    for bad in ({"ta": {"speaker": 5}}, {"hi": {"x": 1}}, {"xx": {}}):
        with pytest.raises(ValueError):
            settings.apply_choices(bad)


# ---------- text normalisation ----------
@pytest.mark.parametrize("n,words", [
    (0, "शून्य"), (7, "सात"), (99, "निन्यानवे"), (100, "एक सौ"), (1234567, "बारह लाख चौंतीस हज़ार पाँच सौ सड़सठ"),
    (150_000_000, "पंद्रह करोड़"), (120_000_000_000, "बारह हज़ार करोड़"), (1_200_000_000_000, "एक लाख बीस हज़ार करोड़")])
def test_hindi_indian_grouping(n, words):
    assert textnorm.hi_words(n) == words


def test_english_indian_grouping():
    assert textnorm.normalize_text("Rs 12,34,567", "en", "indian") == "twelve lakh thirty-four thousand five hundred sixty-seven rupees"
    assert textnorm.normalize_text("5 crore", "en", "indian") == "five crore"


def test_english_western_percent_year_date():
    t = textnorm.normalize_text("In 2026, 3.2% on 2026-03-14 and Q3 stays", "en")
    assert "twenty twenty-six" in t and "three point two percent" in t
    assert "the fourteenth of March, twenty twenty-six" in t and "Q3" in t


def test_currency_per_language():
    assert textnorm.normalize_text("₹12,34,567", "hi", "indian") == "बारह लाख चौंतीस हज़ार पाँच सौ सड़सठ रुपये"
    assert textnorm.normalize_text("₹5 करोड़", "hi", "indian") == "पाँच करोड़ रुपये"
    assert textnorm.normalize_text("$1.500", "es") == "mil quinientos dólares"
    assert textnorm.normalize_text("R$ 2.500", "pt") == "dois mil e quinhentos reais"
    assert textnorm.normalize_text("1234567円", "ja") == "百二十三万四千五百六十七円"
    assert textnorm.normalize_text("$1.5 million", "en") == "one point five million dollars"


def test_es_pt_decimal_comma_and_dates():
    assert textnorm.normalize_text("3,5%", "es") == "tres coma cinco por ciento"
    assert textnorm.normalize_text("2026-03-14", "es") == "catorce de marzo de dos mil veintiséis"
    assert textnorm.normalize_text("2026-03-14", "ja") == "二千二十六年三月十四日"
    assert textnorm.normalize_text("2026-03-14", "hi").startswith("चौदह मार्च")
    assert textnorm.normalize_text("2026-02-30", "es") == "dos mil veintiséis, dos, treinta"  # impossible date: parts read


def test_arabic_percent_and_passthrough():
    assert textnorm.normalize_text("3%", "ar") == "ثلاثة في المئة"
    assert textnorm.normalize_text("3.2% 14", "ta") == "3.2% 14"  # no verified rules: digits unchanged
    assert "ta" not in textnorm.VERBALIZED and "kn" not in textnorm.VERBALIZED


# ---------- prosody ----------
def test_pauses_by_punctuation():
    s = prosody.split_sentences("Rates rose. Did they? Yes! Wait... Fine.")
    assert [p for _, p in s] == [0.42, 0.48, 0.40, 0.55, 0.0]
    assert [t for t, _ in s][1] == "Did they?"


def test_abbreviation_and_decimal_not_split():
    s = prosody.split_sentences("Dr. Rao said the rate is 3.2 percent. Next.")
    assert len(s) == 2 and s[0][0].startswith("Dr. Rao")


def test_paragraph_pause_and_scripts():
    s = prosody.split_sentences("One.\n\nTwo।")
    assert s[0][1] == 0.80 and s[1][1] == 0.0
    assert len(prosody.split_sentences("今日は晴れです。明日は雨です。")) == 2
    assert len(prosody.split_sentences("هل ارتفعت؟ نعم.")) == 2


def test_long_sentence_split_at_commas():
    long = ", ".join(["word " * 6 for _ in range(6)]) + "."
    s = prosody.split_sentences(long)
    assert len(s) > 1 and all(len(t.split()) <= prosody.MAX_WORDS for t, _ in s)


def test_join_with_pauses_length():
    a = Wav(np.ones(1000, np.float32), 1000)
    out = prosody.join_with_pauses([(a, 0.5), (a, 0.0)])
    assert len(out.samples) == 2500


# ---------- post-processing ----------
def test_postprocess_keeps_level_and_adds_fixed_room_tone():
    w = speechlike(3.0, 24000)
    p = post.postprocess(w)
    assert p.sr == w.sr and len(p.samples) == len(w.samples) and np.max(np.abs(p.samples)) <= 0.98
    sil = post.postprocess(Wav(np.zeros(24000, np.float32), 24000))
    rms_db = 20 * np.log10(np.sqrt(np.mean(sil.samples ** 2)) + 1e-12)
    assert -66 < rms_db < -60


def test_highpass_removes_rumble_and_deess_reduces_sibilance():
    sr = 24000; t = np.arange(sr) / sr
    assert np.std(post.highpass(np.sin(2 * np.pi * 20 * t), sr)) < 0.1
    sib = np.sin(2 * np.pi * 7000 * t) * 0.5 + np.sin(2 * np.pi * 300 * t) * 0.05
    assert np.std(post.deess(sib, sr)) < np.std(sib) * 0.9


# ---------- naturalness ----------
def test_speechlike_passes_and_noise_or_silence_or_clipping_fail():
    assert naturalness.score(speechlike(8.0, 24000)).passed
    rng = np.random.default_rng(1)
    noise = Wav((rng.standard_normal(24000 * 5) * 0.2).astype(np.float32), 24000)
    assert not naturalness.score(noise).passed
    assert not naturalness.score(Wav(np.zeros(24000 * 3, np.float32), 24000)).passed
    clipped = Wav(np.clip(speechlike(5.0).samples * 20, -1, 1), 24000)
    assert any("clipping" in f for f in naturalness.score(clipped).failures)


def test_monotone_fails_pitch_variance():
    sr = 24000; t = np.arange(sr * 6) / sr
    mono = Wav((np.sin(2 * np.pi * 120 * t) * np.clip(np.sin(2 * np.pi * 3.5 * t), 0, None)).astype(np.float32) * 0.3, sr)
    r = naturalness.score(mono)
    assert any("pitch_std" in f for f in r.failures)


def test_extra_scorer_blends():
    r = naturalness.score(speechlike(6.0), extra_scorer=lambda w: 0.0)
    assert r.score <= 50


# ---------- narrate: gate, retry, flag, settings plumbing ----------
class RecEngine:
    name = "rec"; clones_voice = False; uses_settings = True

    def __init__(self, good=True):
        self.calls = []; self.good = good

    def supports(self, lang): return True

    def synth(self, text, lang, ref, settings=None):
        self.calls.append((text, settings))
        if self.good:
            return speechlike(max(1.0, len(text.split()) / 2.6), seed=len(text))
        rng = np.random.default_rng(len(text))
        return Wav((rng.standard_normal(24000) * 0.2).astype(np.float32), 24000)


@pytest.fixture
def rec(monkeypatch):
    monkeypatch.delenv("ULLASLAB_TTS_FORCE", raising=False)
    e = RecEngine()
    base.register_engine("kokoro", lambda: e)
    base.register_engine("chatterbox", lambda: e)
    yield e
    base._FACTORIES.clear(); base._CACHE.clear()


def test_narrate_sentence_level_with_verbalised_text(rec):
    w = narrate("Rates rose 3.2%. Then they fell.", "en", ref_wav="x.wav", engine="kokoro", gate=False)
    assert [c[0] for c in rec.calls] == ["Rates rose three point two percent.", "Then they fell."]
    assert rec.calls[0][1]["effective_cfg_weight"] == 0.5 and w.flags == []
    assert w.engine == "kokoro"  # kept through post-processing so synth_segments can pin one engine per track
    assert narrate("Hello there.", "en", engine="kokoro", gate=False, normalize=False).engine == "kokoro"


def test_narrate_regenerates_once_then_flags(monkeypatch):
    e = RecEngine(good=False)
    base.register_engine("kokoro", lambda: e)
    w = narrate("One sentence here.", "en", engine="kokoro")
    assert len(e.calls) == 2 and e.calls[1][1]["seed"] == 1 and e.calls[1][1]["temperature"] < e.calls[0][1]["temperature"]
    assert w.flags and w.flags[0].startswith("naturalness:")
    base._FACTORIES.clear(); base._CACHE.clear()


def test_resolve_ref_prefers_clip_dir(tmp_path):
    (tmp_path / "ref.wav").write_bytes(b"x"); (tmp_path / "clips").mkdir()
    assert resolve_ref(tmp_path / "ref.wav", 2) == tmp_path / "ref.wav"
    (tmp_path / "clips" / "clip2.wav").write_bytes(b"x")
    assert resolve_ref(tmp_path / "ref.wav", 2) == tmp_path / "clips" / "clip2.wav"
    assert resolve_ref(None, 1) is None


def test_parler_speaker_pick():
    from ullaslab_engine.tts.parler_engine import pick_speaker
    assert pick_speaker("ta", {"speaker": 1}) == "Kavitha"
    assert pick_speaker("hi", None) == "Rohit"
    assert pick_speaker("hi", {"speakers": ["A"], "speaker": 9}) == "A"


# ---------- prepare: QA, denoise, clip selection (synthetic recordings only) ----------
def _recording(snr_noise=0.003, seconds=40.0, reverb=False, seed=3):
    w = speechlike(seconds, 48000, seed=seed, level=0.3)
    rng = np.random.default_rng(seed)
    x = w.samples + snr_noise * rng.standard_normal(len(w.samples)).astype(np.float32)
    if reverb:
        n = int(0.9 * 48000); ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.25 * 48000)); ir[0] = 1
        x = np.convolve(x, ir / np.abs(ir).sum() * 2, "full")[: len(x)].astype(np.float32)
    return Wav(x, 48000)


def test_qa_ok_vs_noisy_vs_clipped():
    ok = prepare.analyze(_recording())
    assert ok.verdict in ("OK", "OK_WITH_NOTES") and ok.metrics["snr_db"] > 25
    noisy = prepare.analyze(_recording(snr_noise=0.1))
    assert noisy.verdict == "RE_RECORD" and any("SNR" in r for r in noisy.reasons)
    clip = Wav(np.clip(_recording().samples * 6, -1, 1), 48000)
    assert prepare.analyze(clip).verdict == "RE_RECORD"


def test_qa_reports_low_source_rate():
    r = prepare.analyze(_recording(), source_sr=16000)
    assert r.verdict == "RE_RECORD" and any("sample rate" in x for x in r.reasons)


def test_denoise_lowers_noise_floor_and_keeps_speech():
    w = _recording(snr_noise=0.02)
    d = prepare.denoise(w)
    _, db0 = prepare._frame_db(w.samples.astype(np.float64), w.sr)
    _, db1 = prepare._frame_db(d.samples.astype(np.float64), d.sr)
    assert np.percentile(db1, 10) < np.percentile(db0, 10) - 4
    assert np.percentile(db1, 90) > np.percentile(db0, 90) - 3


def test_tighten_pauses_caps_gaps():
    sr = 24000; s = speechlike(1.0, sr).samples
    x = np.concatenate([np.zeros(sr * 2, np.float32), s, np.zeros(sr * 3, np.float32), s, np.zeros(sr * 2, np.float32)])
    out = prepare.tighten_pauses(Wav(x, sr))
    assert len(out.samples) / sr < 1 + 1 + 0.6 + 0.4 + 0.5 and len(out.samples) / sr > 2.2


def test_preprocess_outputs_mono_24k_normalised():
    p = prepare.preprocess(_recording(seconds=20), 24000)
    assert p.sr == 24000 and p.samples.ndim == 1
    assert -24.5 < prepare.loudness_lufs(p) < -21.5


def test_select_clips_nonoverlapping_in_range():
    sr = 24000
    seg = speechlike(2.2, sr, seed=5).samples
    gap = np.zeros(int(0.4 * sr), np.float32)
    x = np.concatenate([np.concatenate([seg, gap]) for _ in range(30)])
    clips = prepare.select_clips(Wav(x, sr))
    assert len(clips) == 3
    for c in clips:
        assert 10 <= c["end"] - c["start"] <= 15 and c["total"] > 0
    spans = sorted((c["start"], c["end"]) for c in clips)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_clip_score_penalises_clicks_and_wobbly_pitch():
    sr = 24000
    good = speechlike(12.0, sr, seed=2).samples
    clicky = good.copy(); clicky[::997] += 0.9
    assert prepare._score_window(clicky, sr)["total"] < prepare._score_window(good, sr)["total"]
    t = np.arange(12 * sr) / sr
    wob = (np.sin(2 * np.pi * np.cumsum(120 * 2 ** (np.sin(2 * np.pi * 0.3 * t) * 1.2)) / sr) * 0.3).astype(np.float32)
    assert prepare._score_window(wob, sr)["steady_pitch"] < prepare._score_window(good, sr)["steady_pitch"]


def test_write_clips_roundtrip(tmp_path):
    w = speechlike(12.0, 24000)
    paths = prepare.write_clips(w, [{"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}], tmp_path)
    assert [p.name for p in paths] == ["clip1.wav", "clip2.wav"]
    assert abs(sf.info(str(paths[0])).duration - 5.0) < 0.01


# ---------- demo ----------
def test_demo_plan_covers_13_languages_and_variant_counts():
    rows = demo.plan()
    langs = {r["lang"] for r in rows}
    assert len(langs) == 13
    assert sum(r["lang"] == "es" for r in rows) == 6 and sum(r["lang"] == "en" for r in rows) == 3
    assert sum(r["lang"] == "ta" for r in rows) == 2
    assert set(demo.PASSAGES) == langs


def test_demo_render_writes_local_index_and_choices_form(tmp_path):
    refs = tmp_path / "refs"; refs.mkdir()
    for i in (1, 2, 3):
        sf.write(str(refs / f"clip{i}.wav"), speechlike(1.0).samples, 24000)

    def fake(text, lang, ref, overrides=None):
        return speechlike(6.0, 24000, seed=len(text))
    idx = demo.render_demo(tmp_path / "out", refs, fake, langs=["hi", "ta"], passages={"hi": "नमस्ते।", "ta": "வணக்கம்."})
    h = idx.read_text(encoding="utf-8")
    assert h.count("<audio") == 6 + 2 and "Save choices.json" in h and "http" not in h.replace("application/json", "")
    rows = json.loads((tmp_path / "out" / "variants.json").read_text())
    assert all("file" in r for r in rows)
    assert len(list((tmp_path / "out" / "audio").glob("*.wav"))) == 8


def test_demo_skips_missing_clip_and_failed_engine(tmp_path):
    def boom(text, lang, ref, overrides=None):
        raise RuntimeError("model missing")
    idx = demo.render_demo(tmp_path / "o", None, boom, langs=["hi", "ta"], passages={"hi": "x", "ta": "y"})
    rows = json.loads((tmp_path / "o" / "variants.json").read_text())
    assert all(r.get("skipped") for r in rows) and idx.exists()


def test_demo_second_run_keeps_other_languages(tmp_path):
    ok = lambda text, lang, ref, overrides=None: speechlike(3.0, 24000, seed=len(text))
    demo.render_demo(tmp_path / "o", None, ok, langs=["ta"], passages={"ta": "y"})
    demo.render_demo(tmp_path / "o", None, ok, langs=["te"], passages={"te": "z"})
    rows = json.loads((tmp_path / "o" / "variants.json").read_text())
    assert {r["lang"] for r in rows} == {"ta", "te"} and (tmp_path / "o" / "index.html").read_text(encoding="utf-8").count("<audio") == 4


def test_no_audio_files_are_tracked():
    import subprocess
    from ullaslab_engine.config import ROOT
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in files if f.lower().endswith((".wav", ".m4a", ".mp3", ".flac", ".aiff", ".npy", ".pt"))
               ]
