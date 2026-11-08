"""Presigned-URL transport for the public engine. All inputs arrive and outputs leave through
presigned R2 URLs in the repository_dispatch payload. URLs are secrets: masked, never logged,
never included in exceptions."""
from __future__ import annotations
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

ALLOWED_SUFFIX = ".r2.cloudflarestorage.com"
MAX_BUNDLE_BYTES = 200 * 1024 * 1024
MAX_UNZIPPED_BYTES = 500 * 1024 * 1024
MAX_MODEL_BYTES = 6 * 1024**3  # Parler weights archive (about 4 GB)
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class TransferError(RuntimeError):
    """Transport failure. Message never contains a URL."""


def allowed_hosts_ok(url: str) -> bool:
    u = urlparse(url)
    host = u.hostname or ""
    extra = [h for h in os.environ.get("ULLASLAB_ALLOWED_HOSTS", "").split(",") if h]  # tests only
    if u.scheme == "https":
        return host.endswith(ALLOWED_SUFFIX) or host in extra
    if u.scheme == "http":
        return host in extra
    return False


def validate_payload(p: dict) -> dict:
    """Shape + host allow-list check. Raises TransferError without echoing any value."""
    need = ("job_id", "bundle_url", "languages", "outputs")
    for k in need:
        if k not in p:
            raise TransferError(f"payload missing field {k}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(p["job_id"])):
        raise TransferError("bad job_id")
    clips = p.get("voice_clip_urls") or {}
    if not isinstance(clips, dict) or not all(k in ("1", "2", "3") for k in clips):
        raise TransferError("bad voice_clip_urls")
    model = p.get("model")
    if model is not None:  # WP12: {url, sha256, revision, size} for the Parler weights archive
        if not (isinstance(model, dict) and set(model) == {"url", "sha256", "revision", "size"}
                and re.fullmatch(r"[0-9a-f]{64}", str(model["sha256"]))
                and re.fullmatch(r"[0-9a-f]{40}", str(model["revision"]))
                and isinstance(model["size"], int) and 0 < model["size"] <= MAX_MODEL_BYTES):
            raise TransferError("bad model")
    urls = ([p["bundle_url"], p.get("voice_url"), p.get("timing_url")] + list(p["outputs"].values())
            + list(clips.values()) + [(model or {}).get("url")])
    for name in p["outputs"]:
        if not _NAME.match(name):
            raise TransferError("bad output name")
    for u in urls:
        if u is not None and not (isinstance(u, str) and allowed_hosts_ok(u)):
            raise TransferError("url rejected: host not allow-listed")
    if not all(re.fullmatch(r"[a-z]{2}", str(l)) for l in p["languages"]):
        raise TransferError("bad language code")
    return p


def mask_lines(p: dict) -> list[str]:
    """GitHub Actions ::add-mask:: commands for every URL in the payload and its query/path parts."""
    vals = ([p.get("bundle_url"), p.get("voice_url"), p.get("timing_url")] + list(p.get("outputs", {}).values())
            + list((p.get("voice_clip_urls") or {}).values()) + [(p.get("model") or {}).get("url")])
    out = []
    for v in vals:
        if not v:
            continue
        u = urlparse(v)
        for piece in {v, u.query, u.path.strip("/")}:
            if piece and "\n" not in piece:
                out.append(f"::add-mask::{piece}")
    return out


def download(url: str, dest: Path, max_bytes: int = MAX_BUNDLE_BYTES) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as r:
            r.raise_for_status()
            n = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    n += len(chunk)
                    if n > max_bytes:
                        raise TransferError("download too large")
                    f.write(chunk)
    except requests.RequestException as e:
        raise TransferError(f"download failed ({type(e).__name__})") from None
    return dest


def upload(url: str, path: Path, content_type: str = "application/octet-stream") -> None:
    try:
        with open(path, "rb") as f:
            r = requests.put(url, data=f, headers={"Content-Type": content_type}, timeout=(10, 600))
        r.raise_for_status()
    except requests.RequestException as e:
        raise TransferError(f"upload failed ({type(e).__name__})") from None


def safe_unzip(zpath: Path, dest: Path) -> None:
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest not in target.parents and target != dest:
                raise TransferError("zip entry escapes target")
            total += info.file_size
            if total > MAX_UNZIPPED_BYTES:
                raise TransferError("bundle too large when unzipped")
        z.extractall(dest)


def load_payload(path: Path) -> dict:
    """Read client_payload from a GITHUB_EVENT_PATH file (or a bare payload JSON)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_payload(d.get("client_payload", d))
