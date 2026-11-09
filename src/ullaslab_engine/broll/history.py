"""Per-channel used-clip history so the same clip is not reused across recent episodes."""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path


class History:
    def __init__(self, path: Path, recent: int = 10):
        self.path = Path(path)
        self.recent = recent
        self.data = {"episodes": []}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass

    def blocked(self, current_episode: str) -> set[str]:
        eps = [e for e in self.data["episodes"] if e["episode"] != current_episode][-self.recent:]
        return {k for e in eps for k in e["clips"]}

    def record(self, episode: str, keys: list[str]):
        self.data["episodes"] = [e for e in self.data["episodes"] if e["episode"] != episode]
        self.data["episodes"].append({"episode": episode, "date": date.today().isoformat(), "clips": sorted(set(keys))})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
