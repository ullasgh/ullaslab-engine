"""B-roll provider interface, shared HTTP behaviour (cache, bounded retries, request budget) and licence types.

Hard rules: never fall back to a paid service, never log or cache API keys, one download per asset."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

USER_AGENT = "ullaslab-engine/0.1 (+https://learn.ullaslab.co.in; educational macro videos)"
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
SECRET_PARAMS = {"key", "api_key", "apikey", "token"}


class BrollError(Exception):
    pass


class BudgetExceeded(BrollError):
    pass


class ProviderDisabled(BrollError):
    pass


class LicenceRejected(BrollError):
    pass


@dataclass
class LicenceRecord:
    name: str
    url: str
    creator: str = ""
    attribution: str = ""          # text to show/credit; empty when none required
    credit_required: bool = False
    notice: str = ""               # e.g. "NASA, no endorsement"
    source_url: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    provider: str
    id: str
    title: str = ""
    page_url: str = ""
    download_url: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    creator: str = ""
    tags: list[str] = field(default_factory=list)
    thumb_url: str = ""
    licence: LicenceRecord | None = None
    local_path: str = ""           # set by manual import / after fetch
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        return "landscape" if self.width >= self.height else "portrait"

    def text(self) -> str:
        return " ".join([self.title, *self.tags])


def _scrub(params: dict | None) -> dict:
    return {k: v for k, v in sorted((params or {}).items()) if k.lower() not in SECRET_PARAMS}


class Http:
    """requests wrapper: JSON metadata cache, bounded retries with backoff on 429/5xx, per-provider spacing,
    and a hard request budget (global and per provider). Secrets are never part of cache keys or errors."""

    def __init__(self, cache_dir: Path, *, total_budget: int = 200, retries: int = 3, backoff: float = 1.0,
                 session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.cache_dir = Path(cache_dir)
        self.total_budget = total_budget
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.sleep = sleep
        self.clock = clock
        self.used = 0
        self.per_provider: dict[str, int] = {}
        self.limits: dict[str, dict] = {}   # provider -> {min_interval_s, max_requests}
        self._last: dict[str, float] = {}
        self.cache_hits = 0

    def configure(self, provider: str, *, min_interval_s: float = 0.0, max_requests: int | None = None):
        self.limits[provider] = {"min_interval_s": min_interval_s, "max_requests": max_requests}

    def _spend(self, provider: str):
        lim = self.limits.get(provider, {})
        if self.used >= self.total_budget:
            raise BudgetExceeded(f"run request budget {self.total_budget} exhausted")
        cap = lim.get("max_requests")
        if cap is not None and self.per_provider.get(provider, 0) >= cap:
            raise BudgetExceeded(f"{provider} request budget {cap} exhausted")
        gap = lim.get("min_interval_s", 0.0)
        last = self._last.get(provider)
        if gap and last is not None:
            wait = gap - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last[provider] = self.clock()
        self.used += 1
        self.per_provider[provider] = self.per_provider.get(provider, 0) + 1

    def _request(self, provider: str, url: str, *, params=None, headers=None, stream=False) -> requests.Response:
        last_status = None
        for attempt in range(self.retries + 1):
            self._spend(provider)
            try:
                r = self.session.get(url, params=params, headers=headers, stream=stream, timeout=(10, 60))
            except requests.RequestException as e:
                last_status = type(e).__name__
                r = None
            if r is not None:
                if r.status_code == 429 or r.status_code >= 500:
                    last_status = r.status_code
                    ra = r.headers.get("Retry-After", "")
                    r.close()
                    delay = min(float(ra), 60.0) if ra.replace(".", "", 1).isdigit() else self.backoff * (2 ** attempt)
                    if attempt < self.retries:
                        self.sleep(delay)
                    continue
                if r.status_code >= 400:
                    code = r.status_code
                    r.close()
                    raise BrollError(f"{provider}: HTTP {code}")
                return r
            if attempt < self.retries:
                self.sleep(self.backoff * (2 ** attempt))
        raise BrollError(f"{provider}: giving up after {self.retries + 1} attempts (last {last_status})")

    def get_json(self, provider: str, url: str, *, params=None, headers=None) -> Any:
        ck = hashlib.sha256(json.dumps([provider, url, _scrub(params)], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / "meta" / f"{ck}.json"
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        r = self._request(provider, url, params=params, headers=headers)
        try:
            data = r.json()
        except ValueError as e:
            raise BrollError(f"{provider}: response was not JSON") from e
        finally:
            r.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def download(self, provider: str, url: str, dest: Path, headers=None) -> Path:
        if dest.exists() and dest.stat().st_size > 0:
            self.cache_hits += 1
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        r = self._request(provider, url, headers=headers, stream=True)
        n = 0
        try:
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    n += len(chunk)
                    if n > MAX_DOWNLOAD_BYTES:
                        raise BrollError(f"{provider}: download exceeds size cap")
                    f.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            r.close()
        tmp.replace(dest)
        return dest


class BrollProvider(ABC):
    name = "base"
    needs_key = False
    default_enabled = True

    def __init__(self, http: Http | None = None, cache_dir: Path | None = None, options: dict | None = None):
        self.http = http
        self.cache_dir = Path(cache_dir) if cache_dir else (http.cache_dir if http else Path("out/broll-cache"))
        self.options = options or {}

    @abstractmethod
    def search(self, query: str, orientation: str = "landscape", min_res: int = 1080,
               duration: tuple[float, float] = (0.0, 600.0)) -> list[Candidate]: ...

    @abstractmethod
    def fetch(self, candidate: Candidate) -> Path: ...

    @abstractmethod
    def licence(self, candidate: Candidate) -> LicenceRecord: ...

    # shared helpers
    def asset_path(self, candidate: Candidate, ext: str) -> Path:
        h = hashlib.sha256(candidate.key.encode()).hexdigest()[:24]
        return self.cache_dir / "assets" / self.name / f"{h}{ext}"

    def _fetch_url(self, candidate: Candidate, headers=None) -> Path:
        if not candidate.download_url:
            raise BrollError(f"{candidate.key}: no download url")
        ext = Path(candidate.download_url.split("?")[0]).suffix.lower() or ".mp4"
        return self.http.download(self.name, candidate.download_url, self.asset_path(candidate, ext), headers=headers)


def keep_candidate(c: Candidate, orientation: str, min_res: int, duration: tuple[float, float],
                   hard_res: bool = False) -> bool:
    """Orientation and duration are hard filters; resolution is a preference (see select_order) unless hard_res."""
    if c.orientation not in ("unknown", orientation) and orientation in ("landscape", "portrait"):
        return False
    if c.duration and not (duration[0] <= c.duration <= duration[1]):
        return False
    if hard_res and c.width and min(c.width, c.height) < min_res:
        return False
    return True


def res_score(c: Candidate, min_res: int) -> tuple[int, int]:
    short = min(c.width, c.height) if c.width and c.height else 0
    return (1 if short >= min_res else 0, short)


def tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 2}


def probe(path: Path) -> dict:
    """ffprobe width/height/duration of a local file ({} on failure)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        j = json.loads(out)
        s = (j.get("streams") or [{}])[0]
        return {"width": int(s.get("width", 0)), "height": int(s.get("height", 0)),
                "duration": float(j.get("format", {}).get("duration", 0) or 0)}
    except (subprocess.SubprocessError, ValueError, OSError):
        return {}


def load_env(root: Path) -> dict[str, str]:
    """Process env plus a minimal .env parse (no dotenv dependency). Values are never printed."""
    env: dict[str, str] = {}
    files = [root / ".env"]
    try:
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True,
                                text=True, timeout=10).stdout.strip()
        if common:
            files.append((root / common).resolve().parent / ".env")
    except (subprocess.SubprocessError, OSError):
        pass
    if os.environ.get("ULLASLAB_ENV_FILE"):
        files.insert(0, Path(os.environ["ULLASLAB_ENV_FILE"]))
    for f in reversed(files):
        if f.is_file():
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k in env or k.endswith("_API_KEY")})
    return env
