"""Rank candidate clips against a scene: open_clip ViT-B-32 (CPU) text-image similarity on 3 ffmpeg-sampled frames,
minus a penalty for visible text/logos. If open_clip is not installed, FallbackRanker (metadata keyword overlap,
no frame analysis, no logo detection) is used and the ledger records which ranker ran."""
from __future__ import annotations
import subprocess
from pathlib import Path

from .base import Candidate, probe, tokens

TEXT_PROMPTS = ["a video frame with large text, captions or a watermark", "a company logo or brand name on screen",
                "a clean cinematic video frame without text"]
TEXT_PENALTY_WEIGHT = 0.10


def sample_frames(video: Path, out_dir: Path, n: int = 3) -> list[Path]:
    """Extract n frames at 25/50/75% (evenly spaced inside the clip) as PNGs. Returns paths that were written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = probe(video).get("duration", 0.0) or 0.0
    fracs = [(i + 1) / (n + 1) for i in range(n)]
    paths = []
    for i, f in enumerate(fracs):
        p = out_dir / f"{video.stem}_f{i}.png"
        if not p.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * f:.2f}", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=-2:360", str(p)], capture_output=True, timeout=120)
        if p.exists() and p.stat().st_size > 0:
            paths.append(p)
    return paths


class FallbackRanker:
    name = "fallback-keyword"

    def score(self, cand: Candidate, frames: list[Path], texts: list[str]) -> dict:
        want = set().union(*(tokens(t) for t in texts)) if texts else set()
        have = tokens(cand.text())
        s = len(want & have) / max(1, len(want))
        return {"score": s, "similarity": s, "text_penalty": 0.0, "ranker": self.name}


class ClipRanker:
    name = "open_clip ViT-B-32 (laion2b_s34b_b79k, cpu)"

    def __init__(self):
        import open_clip
        import torch
        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k", device="cpu")
        self.model.eval()
        self.tok = open_clip.get_tokenizer("ViT-B-32")
        self._pen = self._encode_text(TEXT_PROMPTS)

    def _encode_text(self, texts):
        with self.torch.no_grad():
            t = self.model.encode_text(self.tok(texts))
            return t / t.norm(dim=-1, keepdim=True)

    def score(self, cand: Candidate, frames: list[Path], texts: list[str]) -> dict:
        from PIL import Image
        if not frames or not texts:
            return {"score": -1.0, "similarity": -1.0, "text_penalty": 0.0, "ranker": self.name}
        torch = self.torch
        imgs = torch.stack([self.preprocess(Image.open(f).convert("RGB")) for f in frames])
        with torch.no_grad():
            im = self.model.encode_image(imgs)
            im = im / im.norm(dim=-1, keepdim=True)
            tx = self._encode_text(texts)
            sim = (im @ tx.T).max(dim=1).values.mean().item()          # best prompt per frame, mean over frames
            p = (100.0 * im @ self._pen.T).softmax(dim=-1)[:, :2].sum(dim=1).mean().item()
        return {"score": sim - TEXT_PENALTY_WEIGHT * p, "similarity": sim, "text_penalty": p, "ranker": self.name}


def get_ranker(force_fallback: bool = False):
    """Returns (ranker, note). note is non-empty when the fallback is in use."""
    if not force_fallback:
        try:
            return ClipRanker(), ""
        except Exception as e:  # ImportError, offline weights, etc.
            return FallbackRanker(), f"open_clip unavailable ({type(e).__name__}); using fallback keyword ranker"
    return FallbackRanker(), "fallback keyword ranker forced"
