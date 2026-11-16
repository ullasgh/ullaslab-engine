"""Regression tests: pinned model revisions, no redirect following on transfers, dependency updates. Offline: no model is
downloaded and no network is used (the redirect tests talk to a local server on 127.0.0.1)."""
from __future__ import annotations

import http.server
import re
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest
import yaml

from ullaslab_engine import asr
from ullaslab_engine import io as eio
from ullaslab_engine.config import ROOT
from ullaslab_engine.tts import chatterbox_engine, parler_engine

HEX40 = re.compile(r"[0-9a-f]{40}")


# ---- Hugging Face downloads are pinned to commit hashes --------------------------------------------------------
def test_pinned_revisions_are_full_commit_hashes():
    pins = [*asr.WHISPER_REVISIONS.values(), chatterbox_engine.CHATTERBOX_REVISION,
            parler_engine.PARLER_REVISION, parler_engine.T5_REVISION]
    assert pins and all(HEX40.fullmatch(p) for p in pins), pins
    assert set(asr.WHISPER_REVISIONS) >= {"large-v3", "small"}  # the CI default and the fixture-script size


def test_asr_loads_whisper_at_the_pinned_revision(monkeypatch, tmp_path):
    seen = []

    class M:
        def __init__(self, *a, **k):
            seen.append((a, k))

        def transcribe(self, audio, **kw):
            return iter([]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=M))
    monkeypatch.setattr(asr, "_MODEL", {})
    from ullaslab_engine.audio import Wav
    Wav(np.zeros(1600, dtype=np.float32), 16000).save(tmp_path / "a.wav")
    for size in ("large-v3", "small"):
        monkeypatch.setenv("ULLASLAB_ASR_MODEL", size)
        asr.transcribe(tmp_path / "a.wav", "en")
    assert [k["revision"] for _, k in seen] == [asr.WHISPER_REVISIONS["large-v3"], asr.WHISPER_REVISIONS["small"]]


def test_asr_refuses_a_model_size_without_a_pinned_revision(monkeypatch, tmp_path):
    called = []
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=lambda *a, **k: called.append(1)))
    monkeypatch.setattr(asr, "_MODEL", {})
    monkeypatch.setenv("ULLASLAB_ASR_MODEL", "some-user/unpinned-model")
    from ullaslab_engine.audio import Wav
    Wav(np.zeros(1600, dtype=np.float32), 16000).save(tmp_path / "a.wav")
    with pytest.raises(ValueError, match="pinned"):
        asr.transcribe(tmp_path / "a.wav", "en")
    assert not called


def test_chatterbox_downloads_the_pinned_snapshot_not_main(monkeypatch):
    got = {}

    def snapshot_download(**kw):
        got.update(kw)
        return "/cache/snap"

    class Cls:
        @staticmethod
        def from_local(path, device):
            got["local"] = (str(path), device)
            return "model"

        @staticmethod
        def from_pretrained(device):  # the unpinned path (revision "main") must not be used
            raise AssertionError("unpinned from_pretrained was called")

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setitem(sys.modules, "chatterbox", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", types.SimpleNamespace(ChatterboxMultilingualTTS=Cls))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)))
    eng = chatterbox_engine.ChatterboxEngine()
    assert eng._model == "model"
    assert got["revision"] == chatterbox_engine.CHATTERBOX_REVISION and got["repo_id"] == "ResembleAI/chatterbox"
    assert got["local"] == ("/cache/snap", "cpu")


def test_parler_loads_model_and_tokenizers_at_pinned_revisions(monkeypatch):
    calls = []

    class Model:
        config = types.SimpleNamespace(text_encoder=types.SimpleNamespace(_name_or_path="google/flan-t5-large"))

        def to(self, d):
            return self

    class PM:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append(("model", name, kw.get("revision")))
            return Model()

    class Tok:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append(("tok", name, kw.get("revision")))
            return "tok"

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "parler_tts", types.SimpleNamespace(ParlerTTSForConditionalGeneration=PM))
    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoTokenizer=Tok))
    parler_engine.IndicParlerEngine()
    assert calls == [("model", "ai4bharat/indic-parler-tts", parler_engine.PARLER_REVISION),
                     ("tok", "ai4bharat/indic-parler-tts", parler_engine.PARLER_REVISION),
                     ("tok", "google/flan-t5-large", parler_engine.T5_REVISION)]


# ---- allow-listed fetches do not follow redirects --------------------------------------------------------------
class _H(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):
        _H.hits.append(self.path)
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/elsewhere")
            self.end_headers()
        else:
            body = b"payload" if self.path.startswith("/ok") else b"from-the-redirect-target"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_PUT(self):
        _H.hits.append("PUT " + self.path)
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/redirect"):
            self.send_response(307)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/elsewhere")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _H.hits = []
    s = http.server.HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()
    s.server_close()


def test_download_without_redirect_still_works_control(server, tmp_path):
    assert eio.download(server + "/ok", tmp_path / "f").read_bytes() == b"payload"


def test_download_does_not_follow_a_redirect(server, tmp_path):
    with pytest.raises(eio.TransferError, match="redirect"):
        eio.download(server + "/redirect", tmp_path / "f")
    assert _H.hits == ["/redirect"]  # the target was never requested
    assert not (tmp_path / "f").exists() or (tmp_path / "f").read_bytes() == b""


def test_upload_does_not_follow_a_redirect(server, tmp_path):
    f = tmp_path / "o.bin"
    f.write_bytes(b"data")
    eio.upload(server + "/ok", f)  # control
    with pytest.raises(eio.TransferError, match="redirect"):
        eio.upload(server + "/redirect", f)
    assert "PUT /elsewhere" not in _H.hits


# ---- dependabot ------------------------------------------------------------------------------------------------
def test_dependabot_covers_uv_npm_and_actions():
    d = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    assert d["version"] == 2
    eco = {u["package-ecosystem"]: u for u in d["updates"]}
    assert set(eco) == {"uv", "npm", "github-actions"}  # uv: pyproject.toml plus uv.lock
    assert eco["npm"]["directory"] == "/remotion" and eco["uv"]["directory"] == "/" and eco["github-actions"]["directory"] == "/"
    for u in d["updates"]:
        assert u["schedule"]["interval"] in ("weekly", "monthly")
        assert 0 < u["open-pull-requests-limit"] <= 5
