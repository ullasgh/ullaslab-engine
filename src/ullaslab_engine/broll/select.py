"""Per-scene candidate search, pre-score, download of the top few, ranking and selection."""
from __future__ import annotations
import re
import shutil
from datetime import date
from pathlib import Path

from .base import BrollError, Candidate, Http, ProviderDisabled, keep_candidate, probe, res_score, tokens
from .ledger import sha256_file
from .scenes import Scene


LOGO_META = re.compile(r"\b(logo|watermark|watermarked|insignia)\b", re.I)


def queries(scene: Scene) -> list[str]:
    qs = []
    if len(scene.search_terms) > 1:
        qs.append(" ".join(scene.search_terms[:3]))
    qs += scene.search_terms
    if not qs and scene.visual_objective:
        qs.append(" ".join(scene.visual_objective.split()[:6]))
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def prescore(c: Candidate, scene: Scene, min_res: int) -> tuple:
    want = tokens(" ".join(scene.search_terms) + " " + scene.visual_objective)
    overlap = len(want & tokens(c.text())) / max(1, len(want))
    return (res_score(c, min_res)[0], round(overlap, 3), res_score(c, min_res)[1])


def select_scene(scene: Scene, providers: list, ranker, *, orientation: str, min_res: int, top_n: int, blocked: set[str],
                 used: dict[str, str], frames_dir: Path, log: list[str], max_text_penalty: float = 0.7) -> dict | None:
    """Returns {candidate, path, rank, ...} or None. `used` maps clip key/sha -> scene id (episode dedupe)."""
    dur = scene.duration_range()
    pool: dict[str, Candidate] = {}
    texts = [t for t in [scene.visual_objective, *scene.search_terms] if t]
    for prov in providers:
        for q in queries(scene):
            try:
                for c in prov.search(q, orientation, min_res, dur):
                    if c.key not in blocked and c.key not in used:
                        pool.setdefault(c.key, c)
            except ProviderDisabled as e:
                log.append(str(e))
                break
            except BrollError as e:
                log.append(f"{scene.id}: {prov.name} '{q}': {e}")
                if "budget" in str(e):
                    break
        if len(pool) >= top_n:
            break   # earlier providers in config order take priority
    prov_by_name = {p.name: p for p in providers}
    ordered = sorted(pool.values(), key=lambda c: prescore(c, scene, min_res), reverse=True)[: top_n]
    scored = []
    for c in ordered:
        prov = prov_by_name[c.provider]
        try:
            path = prov.fetch(c)
        except BrollError as e:
            log.append(f"{scene.id}: fetch {c.key}: {e}")
            continue
        if not (c.width and c.height):
            info = probe(path)
            c.width, c.height, c.duration = info.get("width", 0), info.get("height", 0), info.get("duration", 0.0)
        if not keep_candidate(c, orientation, min_res, dur):
            log.append(f"{scene.id}: {c.key} dropped after fetch (orientation/duration)")
            continue
        sha = sha256_file(path)
        if sha in used:
            log.append(f"{scene.id}: {c.key} duplicate content of {used[sha]}")
            continue
        from .rank import sample_frames
        frames = sample_frames(path, frames_dir / scene.id)
        r = ranker.score(c, frames, texts)
        if LOGO_META.search(c.text()) or r.get("text_penalty", 0.0) > max_text_penalty:
            log.append(f"{scene.id}: {c.key} rejected (logo/text/watermark)")
            continue
        # resolution preference: >= min_res clips beat sub-1080 ones, then similarity
        scored.append(((1 if min(c.width, c.height) >= min_res else 0), r["score"], c, path, r, sha, frames))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    _, _, c, path, r, sha, frames = scored[0]
    return {"candidate": c, "path": path, "rank": r, "sha256": sha, "frames": [str(f) for f in frames],
            "considered": [{"key": t[2].key, **{k: v for k, v in t[4].items() if k != "ranker"}} for t in scored],
            "low_res": min(c.width, c.height) < min_res}
