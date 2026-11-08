import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from ullaslab_engine.audio import Wav
from ullaslab_engine.config import ROOT


def speechlike(seconds: float, sr: int = 24000, seed: int = 0, level: float = 0.3) -> Wav:
    """Voiced-speech-like signal: harmonics of a wobbling 120 Hz pitch, syllable envelope, a little
    noise. Crest factor is in the range of real TTS output; no model needed."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    f0 = 120 + 15 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    x = sum(np.sin(h * phase) / h for h in range(1, 12))
    env = np.clip(np.sin(2 * np.pi * 3.5 * t), 0, None) ** 1.5
    x = (x * env + 0.05 * rng.standard_normal(n) * env)
    x = x / np.max(np.abs(x)) * level * 3
    return Wav(np.clip(x, -1, 1).astype(np.float32), sr)


@pytest.fixture
def bundle_dir(tmp_path) -> Path:
    d = tmp_path / "work" / "bundle"
    shutil.copytree(ROOT / "fixtures" / "fixture-bundle", d)
    return d


@pytest.fixture
def work(bundle_dir) -> Path:
    return bundle_dir.parent


def fake_tts_factory(words_per_s: float = 2.6):
    """tts_fn stand-in: duration proportional to word count, deterministic."""
    def fake(text, lang, ref, normalize=True, engine=None):
        w = speechlike(max(0.8, len(text.split()) / words_per_s), seed=len(text))
        return w
    return fake
