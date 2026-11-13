"""Pinned V3 weights loader (tts/chatterbox_engine.py): constants, hash check, link directory, variant routing. No model and no
network: the download and the model class are fakes."""
from __future__ import annotations

import hashlib
import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from ullaslab_engine.tts import chatterbox_engine as CE
from ullaslab_engine.tts.base import EngineUnavailable


def test_pin_is_an_exact_revision_and_every_hash_is_a_sha256():
    assert re.fullmatch(r"[0-9a-f]{40}", CE.V3_REVISION)
    assert CE.V3_FILE in CE.V3_SHA256 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in CE.V3_SHA256.values())
    assert CE.T3_VARIANTS == ("v2", "v3")


def _fake_snapshot(tmp_path, contents):
    d = tmp_path / "snap"
    d.mkdir()
    for name, data in contents.items():
        (d / name).write_bytes(data)

    def dl(**kw):
        assert kw["revision"] == CE.V3_REVISION and kw["repo_id"] == CE.V3_REPO
        assert CE.V3_FILE in kw["allow_patterns"]
        return str(d)
    return dl, d


def test_fetch_verifies_every_pinned_hash(tmp_path, monkeypatch):
    blobs = {n: n.encode() * 3 for n in (*CE.V3_COMPANIONS, CE.V3_FILE)}
    monkeypatch.setattr(CE, "V3_SHA256", {n: hashlib.sha256(blobs[n]).hexdigest() for n in CE.V3_SHA256})
    dl, d = _fake_snapshot(tmp_path, blobs)
    assert CE.fetch_v3(dl) == d
    (d / CE.V3_FILE).write_bytes(b"tampered")
    with pytest.raises(EngineUnavailable) as ei:
        CE.fetch_v3(dl)
    assert ei.value.error_class == "ChecksumMismatch" and CE.V3_FILE in str(ei.value)


def test_checkpoint_dir_presents_the_v3_file_under_the_name_the_pinned_library_reads(tmp_path):
    for n in (*CE.V3_COMPANIONS, CE.V3_FILE):
        (tmp_path / n).write_bytes(b"x")
    with CE.v3_checkpoint_dir(tmp_path) as _:
        pass
    td = CE.v3_checkpoint_dir(tmp_path)
    names = {p.name for p in Path(td.name).iterdir()}
    assert "t3_mtl23ls_v2.safetensors" in names and CE.V3_FILE not in names and "ve.pt" in names
    assert (Path(td.name) / "t3_mtl23ls_v2.safetensors").resolve() == (tmp_path / CE.V3_FILE).resolve()
    td.cleanup()
    assert not Path(td.name).exists()


class _Model:
    sr = 24000

    def __init__(self, tag):
        self.tag, self.calls = tag, []

    def generate(self, text, language_id, audio_prompt_path, **kw):
        import torch
        self.calls.append((text, language_id, kw))
        return torch.zeros(1, 2400)


def test_t3_weights_setting_picks_the_variant_and_loads_each_once(monkeypatch):
    pytest.importorskip("torch")
    loads = []
    e = CE.ChatterboxEngine.__new__(CE.ChatterboxEngine)
    e._models = {}
    monkeypatch.setattr(e, "_load", lambda v: loads.append(v) or _Model(v), raising=False)
    w = e.synth("hello there friend", "en", Path("ref.wav"), settings={"seed": 1, "t3_weights": "v3"})
    e.synth("hello again friend", "en", Path("ref.wav"), settings={"seed": 2, "t3_weights": "v3"})
    e.synth("hola amigo", "es", Path("ref.wav"), settings={"seed": 1})               # no setting: the V2 weights, as before
    assert loads == ["v3", "v2"] and isinstance(w.samples, np.ndarray) and w.sr == 24000
    with pytest.raises(EngineUnavailable):
        e.synth("x", "en", Path("ref.wav"), settings={"t3_weights": "v9"})


def test_engine_constructor_still_reports_a_missing_extra_as_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "chatterbox", None)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", None)
    with pytest.raises(ImportError):
        CE.ChatterboxEngine()
