"""Tolerant scenes.json reader. Fields used: id, type, visual_objective, search_terms[], illustrative and the narration
span (start/end seconds under narration_span / narration / top level, or a duration). Unknown fields are ignored."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

FOOTAGE_TYPES = {"footage", "broll", "b-roll", "stock", "video"}


@dataclass
class Scene:
    id: str
    visual_objective: str = ""
    search_terms: list[str] = field(default_factory=list)
    illustrative: bool = True
    start: float | None = None
    end: float | None = None
    narration: str = ""
    type: str = "footage"

    @property
    def duration(self) -> float | None:
        if self.start is not None and self.end is not None and self.end > self.start:
            return self.end - self.start
        return None

    def duration_range(self) -> tuple[float, float]:
        d = self.duration
        # stock clips can be trimmed, slowed or looped, so only a floor of min(span, 8s) is demanded
        return (min(d, 8.0) if d else 3.0, 120.0)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _scene(d: dict, i: int) -> Scene:
    span = d.get("narration_span") or d.get("narration") or d.get("span") or {}
    if not isinstance(span, dict):
        span = {}
    start = _num(span.get("start", span.get("start_s", d.get("start", d.get("start_s")))))
    end = _num(span.get("end", span.get("end_s", d.get("end", d.get("end_s")))))
    if start is None and end is None and _num(d.get("duration")):
        start, end = 0.0, _num(d.get("duration"))
    terms = d.get("search_terms") or d.get("search") or []
    if isinstance(terms, str):
        terms = [terms]
    text = span.get("text") if span else None
    if text is None and isinstance(d.get("narration"), str):
        text = d["narration"]
    return Scene(id=str(d.get("id", f"s{i + 1}")), visual_objective=str(d.get("visual_objective") or d.get("objective") or ""),
                 search_terms=[str(t) for t in terms if str(t).strip()], illustrative=bool(d.get("illustrative", True)),
                 start=start, end=end, narration=str(text or ""), type=str(d.get("type", "footage")).lower())


def load_scenes(path: Path, include_all_types: bool = False) -> list[Scene]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValueError("scenes.json: expected a list or an object with a 'scenes' list")
    scenes = [_scene(d, i) for i, d in enumerate(raw) if isinstance(d, dict)]
    return scenes if include_all_types else [s for s in scenes if s.type in FOOTAGE_TYPES]
