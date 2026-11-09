"""`broll fetch`: process footage scenes into <out>/footage/*, assets.json and assets.md."""
from __future__ import annotations
import shutil
from datetime import date
from pathlib import Path

from ..config import ROOT
from .base import Http
from .history import History
from .ledger import write_ledger
from .rank import get_ranker
from .registry import build_providers, load_config
from .scenes import load_scenes
from .select import select_scene


def run_fetch(scenes_path: Path, out: Path, *, channel: str = "default", episode: str | None = None, orientation: str | None = None,
              cache_dir: Path | None = None, history_dir: Path | None = None, config: Path | None = None,
              env: dict | None = None, force_fallback_ranker: bool = False, http: Http | None = None,
              ranker=None, dry_history: bool = False) -> dict:
    cfg = load_config(config)
    run = cfg["run"]
    cache = Path(cache_dir) if cache_dir else ROOT / "out" / "broll-cache"
    http = http or Http(cache, total_budget=run["total_request_budget"], retries=run["retries"], backoff=run["backoff_s"])
    providers, notes = build_providers(cfg, http, env)
    if ranker is None:
        ranker, rnote = get_ranker(force_fallback_ranker)
        if rnote:
            notes.append(rnote)
    episode = episode or Path(scenes_path).resolve().parent.name
    hist = History((Path(history_dir) if history_dir else cache / "history") / f"{channel}.json", run["history_recent_episodes"])
    blocked = hist.blocked(episode)
    out = Path(out)
    (out / "footage").mkdir(parents=True, exist_ok=True)
    entries, report, used_by_output, log = [], [], {}, []
    for scene in load_scenes(scenes_path):
        # Orientation comes from the output's aspect (16:9 landscape, 9:16 portrait); the CLI value is an override only.
        scene_orient = orientation or scene.orientation or "landscape"
        # Clip reuse is blocked within one output. The same clip MAY appear in different outputs (long/short/reel are
        # separate videos); each output gets its own file, and the ledger has one entry per output.
        used = used_by_output.setdefault(scene.output, {})
        res = select_scene(scene, providers, ranker, orientation=scene_orient, min_res=run["min_res"], top_n=run["rank_top_n"],
                           blocked=blocked, used=used, frames_dir=out / "frames", log=log)
        if not res:
            report.append({"scene": scene.id, "output": scene.output, "status": "no-candidate"})
            continue
        c, path = res["candidate"], res["path"]
        used[c.key] = scene.id
        used[res["sha256"]] = scene.id
        fname = f"{scene.output}/{scene.id}{path.suffix.lower()}"
        (out / "footage" / scene.output).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out / "footage" / fname)
        lic = c.licence
        entries.append({"filename": f"footage/{fname}", "scene": scene.id, "output": scene.output, "orientation": scene_orient, "provider": c.provider, "source_url": lic.source_url or c.page_url,
                        "creator": c.creator, "licence": lic.as_dict(), "download_date": date.today().isoformat(),
                        "illustrative": scene.illustrative, "sha256": res["sha256"], "width": c.width, "height": c.height,
                        "duration": round(c.duration, 2), "ranker": res["rank"]["ranker"], "score": round(res["rank"]["score"], 4),
                        "text_penalty": round(res["rank"]["text_penalty"], 4), "low_res": res["low_res"]})
        report.append({"scene": scene.id, "output": scene.output, "status": "ok", "clip": c.key, "score": round(res["rank"]["score"], 4),
                       "considered": res["considered"], "frames": res["frames"]})
    meta = {"item": episode, "channel": channel, "generated": date.today().isoformat(), "orientation": orientation or "per-output aspect",
            "requests_used": http.used, "cache_hits": http.cache_hits, "notes": "; ".join(notes + log) or "none"}
    write_ledger(out, entries, meta)
    if not dry_history:
        hist.record(episode, [r["clip"] for r in report if r.get("clip")])
    return {"entries": entries, "report": report, "notes": notes + log, "http": http}

