"""Chatterbox-Multilingual (MIT) voice clone. Pin version: upstream retired Aug 2026 (feasibility B3).
Languages of ours it covers: en, hi, es, pt, ar, ja. Output carries Resemble's PerTh watermark (kept).

Two T3 weight variants, chosen per synthesis call by the `t3_weights` setting (config: the active delivery profile's
`_options.t3_weights`, default `v2`):
  v2  the weights `chatterbox-tts` 0.1.7 itself downloads (unchanged behaviour, every other language).
  v3  Resemble's "more expressive" multilingual T3 checkpoint. Same architecture and size, so the pinned 0.1.7 code loads it
      as is. Pinned to an exact Hugging Face revision and verified by sha256 before it is used (a moved or tampered file
      refuses to load). The companion files (voice encoder, S3Gen, tokenizer) come from the same pinned revision.
The engine code stays on the PyPI release (0.1.7, uv.lock); only the weights file differs. Licences: THIRD_PARTY_LICENSES.md."""
from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path
import numpy as np
from ..audio import Wav
from .base import EngineUnavailable

_LANGS = {"en", "hi", "es", "pt", "ar", "ja"}

V3_REPO = "ResembleAI/chatterbox"
V3_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"     # repo head on 2026-11-13 (last modified 2026-06-10)
V3_FILE = "t3_mtl23ls_v3.safetensors"
# sha256 of the files that carry the model (huggingface LFS oids at V3_REVISION)
V3_SHA256 = {
    V3_FILE: "5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953",
    "ve.pt": "4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1",
    "s3gen.pt": "9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3",
}
V3_COMPANIONS = ("ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json")
T3_VARIANTS = ("v2", "v3")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def fetch_v3(download=None) -> Path:
    """Local directory holding the pinned V3 checkpoint files (hub cache, offline-capable once cached). Raises on a hash
    mismatch. `download` is a test seam standing in for huggingface_hub.snapshot_download."""
    if download is None:
        from huggingface_hub import snapshot_download as download
    d = Path(download(repo_id=V3_REPO, repo_type="model", revision=V3_REVISION,
                      allow_patterns=[*V3_COMPANIONS, V3_FILE], token=os.getenv("HF_TOKEN")))
    for name, want in V3_SHA256.items():
        got = _sha256(d / name)
        if got != want:
            raise EngineUnavailable(f"chatterbox v3: {name} sha256 mismatch", "ChecksumMismatch")
    return d


def v3_checkpoint_dir(src: Path) -> tempfile.TemporaryDirectory:
    """chatterbox-tts 0.1.7 reads the T3 weights from `t3_mtl23ls_v2.safetensors` inside the checkpoint directory. A directory of
    links to the pinned files, with the V3 file under that name, makes the unchanged 0.1.7 loader read V3 (no library patch)."""
    td = tempfile.TemporaryDirectory(prefix="ullaslab-cb-v3-")
    for name in (*V3_COMPANIONS, V3_FILE):
        if (src / name).exists():
            os.symlink(src / name, Path(td.name) / ("t3_mtl23ls_v2.safetensors" if name == V3_FILE else name))
    return td


class ChatterboxEngine:
    name = "chatterbox"
    clones_voice = True
    uses_settings = True

    def __init__(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # ImportError -> EngineUnavailable
        self._cls = ChatterboxMultilingualTTS
        self._models: dict[str, object] = {}

    def _load(self, variant: str):
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        if variant == "v3":
            td = v3_checkpoint_dir(fetch_v3())
            try:
                return self._cls.from_local(td.name, dev)
            finally:
                td.cleanup()                 # the weights are in memory; the links are not needed any more
        return self._cls.from_pretrained(device=dev)

    def model(self, variant: str = "v2"):
        if variant not in T3_VARIANTS:
            raise EngineUnavailable(f"chatterbox: unknown t3_weights {variant!r}", "ValueError")
        if variant not in self._models:
            self._models[variant] = self._load(variant)
        return self._models[variant]

    def supports(self, lang: str) -> bool:
        return lang in _LANGS

    def synth(self, text: str, lang: str, ref_wav: Path | None, settings: dict | None = None) -> Wav:
        st = settings or {}
        kw = {}
        if "exaggeration" in st:
            kw["exaggeration"] = float(st["exaggeration"])
        if "effective_cfg_weight" in st:  # 0 for native accent on non-English targets (upstream README)
            kw["cfg_weight"] = float(st["effective_cfg_weight"])
        if "temperature" in st:
            kw["temperature"] = float(st["temperature"])
        try:
            import torch
            m = self.model(str(st.get("t3_weights") or "v2"))
            torch.manual_seed(1000 + int(st.get("seed", 0)))
            wav = m.generate(text, language_id=lang, audio_prompt_path=str(ref_wav), **kw)
        except EngineUnavailable:
            raise
        except Exception as e:
            raise EngineUnavailable(f"chatterbox failed: {type(e).__name__}") from None
        arr = wav.detach().cpu().numpy().astype(np.float32).reshape(-1)
        return Wav(arr, int(m.sr))
