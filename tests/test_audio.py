import numpy as np
from conftest import speechlike
from ullaslab_engine.audio import (Wav, assemble, loudness_lufs, max_silence_s, normalize_loudness, resample,
                                   trim_silence, true_peak_dbtp)


def test_normalize_hits_target_and_true_peak():
    for seed, level in [(1, 0.05), (2, 0.3), (3, 0.9)]:
        out = normalize_loudness(speechlike(12, seed=seed, level=level))
        assert abs(loudness_lufs(out) - (-14)) <= 0.5
        assert true_peak_dbtp(out) <= -1.0


def test_silence_is_left_alone():
    w = Wav(np.zeros(24000, dtype=np.float32), 24000)
    assert normalize_loudness(w).samples.max() == 0


def test_assemble_places_clips_and_pads():
    a = Wav(np.ones(1000, dtype=np.float32) * 0.5, 1000)
    out = assemble([(0.0, a), (2.0, a)], 1000, total_s=4.0)
    assert len(out.samples) == 4000
    assert out.samples[500] == 0.5 and out.samples[1500] == 0 and out.samples[2500] == 0.5


def test_trim_and_silence_detection():
    x = np.concatenate([np.zeros(5000), np.ones(2000) * 0.3, np.zeros(30000), np.ones(2000) * 0.3, np.zeros(5000)]).astype(np.float32)
    w = Wav(x, 10000)
    assert len(trim_silence(w, keep_s=0).samples) < len(x)
    assert 2.9 < max_silence_s(trim_silence(w, keep_s=0)) < 3.1


def test_resample_roundtrip_length():
    w = speechlike(1.0, sr=24000)
    assert abs(len(resample(w, 48000).samples) - 48000) <= 1
