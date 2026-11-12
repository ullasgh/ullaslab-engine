import numpy as np
import pytest
from conftest import speechlike
from ullaslab_engine.audio import loudness_lufs
from ullaslab_engine import tts as T
from ullaslab_engine.tts import base
from ullaslab_engine.tts.base import EngineUnavailable, NoVoiceAvailable, plan_engines


class Fake:
    def __init__(self, name, langs, clones=False, fail=False):
        self.name, self.clones_voice, self._l, self._f = name, clones, set(langs), fail
        self.calls = 0

    def supports(self, lang): return lang in self._l

    def synth(self, text, lang, ref):
        self.calls += 1
        if self._f:
            raise EngineUnavailable("boom")
        return speechlike(2.0)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ULLASLAB_TTS_FORCE", raising=False)
    saved = dict(base._FACTORIES), dict(base._CACHE)
    yield
    base._FACTORIES.clear(); base._FACTORIES.update(saved[0]); base._CACHE.clear(); base._CACHE.update(saved[1])


def test_plan_follows_languages_yaml():
    assert plan_engines("en") == ["chatterbox", "kokoro"]
    assert plan_engines("ta") == ["indic_parler"]
    assert plan_engines("ar") == ["chatterbox"]          # no stock fallback for Arabic
    assert plan_engines("hi") == ["chatterbox", "indic_parler"]


def test_clone_engine_used_with_ref_and_output_is_normalised(tmp_path):
    ref = tmp_path / "r.wav"
    base.register_engine("chatterbox", lambda: Fake("chatterbox", ["en"], clones=True))
    w = T.tts("hello", "en", ref)
    assert abs(loudness_lufs(w) + 14) <= 0.5


def test_falls_back_when_primary_fails():
    base.register_engine("chatterbox", lambda: Fake("chatterbox", ["es"], clones=True, fail=True))
    k = Fake("kokoro", ["es"])
    base.register_engine("kokoro", lambda: k)
    T.tts("hola", "es", "ref.wav")
    assert k.calls == 1


def test_missing_ref_skips_clone_engine_to_stock():
    c, k = Fake("chatterbox", ["en"], clones=True), Fake("kokoro", ["en"])
    base.register_engine("chatterbox", lambda: c); base.register_engine("kokoro", lambda: k)
    T.tts("hi", "en", None)
    assert c.calls == 0 and k.calls == 1


def test_no_voice_degrades_to_captions_only():
    base.register_engine("chatterbox", lambda: Fake("chatterbox", ["ar"], clones=True, fail=True))
    with pytest.raises(NoVoiceAvailable):
        T.tts("مرحبا", "ar", "ref.wav")


def test_indic_has_no_cloning_requirement():
    p = Fake("indic_parler", ["ta"])
    base.register_engine("indic_parler", lambda: p)
    T.tts("வணக்கம்", "ta", None)
    assert p.calls == 1


def test_force_env_overrides(monkeypatch):
    monkeypatch.setenv("ULLASLAB_TTS_FORCE", "kokoro")
    assert plan_engines("ar") == ["kokoro"]


def test_unknown_engine_and_missing_extra():
    with pytest.raises(EngineUnavailable):
        base.get_engine("nope")


def test_engine_contract_declared_for_builtin_languages():
    from ullaslab_engine.config import languages
    for code, cfg in languages().items():
        assert cfg["tts_engine"] in ("chatterbox", "indic_parler", "kokoro", "none")
        assert cfg["tts_engine"] != "indicf5"   # licence UNCLEAR, never default


def test_engine_pinned_per_track(bundle_dir):
    from ullaslab_engine.bundle import load_bundle
    from ullaslab_engine.synth import synth_segments
    calls = []
    def tts_fn(text, lang, ref, normalize=True, engine=None):
        calls.append(engine)
        w = speechlike(1.0); w.engine = "kokoro"; return w
    synth_segments(load_bundle(bundle_dir), "en", None, tts_fn)
    assert calls[0] is None and set(calls[1:]) == {"kokoro"}


def test_failures_name_engine_and_exception_class_only():
    class Boom(Fake):
        def synth(self, text, lang, ref):
            raise EngineUnavailable("indic_parler failed: ValueError", "ValueError")
    base.register_engine("indic_parler", lambda: Boom("indic_parler", ["ta"]))
    with pytest.raises(NoVoiceAvailable) as e:
        T.tts("வணக்கம்", "ta", None)
    assert e.value.failures == [("indic_parler", "ValueError")]


def test_engine_that_cannot_load_is_recorded_with_its_class():
    def factory():
        raise OSError("/secret/path/weights missing")
    base.register_engine("chatterbox", factory)
    with pytest.raises(NoVoiceAvailable) as e:
        T.tts("مرحبا", "ar", "ref.wav")
    assert e.value.failures == [("chatterbox", "OSError")]
