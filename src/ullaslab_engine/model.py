"""Indic Parler-TTS weights from the owner's private R2 mirror (WP12). The dispatch carries ONE presigned GET
URL for a tar of a Hugging Face hub cache plus its sha256; no Hugging Face token exists in this repo. The
archive is verified, extracted into a dedicated hub cache (HF_HUB_CACHE for the TTS step, HF_HUB_OFFLINE=1)
and marked, so a restored actions/cache entry downloads nothing."""
from __future__ import annotations
import hashlib
import hmac
import shutil
import tarfile
from pathlib import Path

from .io import MAX_MODEL_BYTES, TransferError, download

MARKER_PREFIX = ".ok-"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(tar_path: Path, hub: Path) -> None:
    hub.mkdir(parents=True)
    total = 0
    with tarfile.open(tar_path) as t:
        members = t.getmembers()
        for m in members:
            top = Path(m.name).parts[:1]
            if not top or not top[0].startswith("models--") or not (m.isfile() or m.isdir() or m.issym()):
                raise TransferError("model archive has an unexpected entry")
            total += m.size
        if total > MAX_MODEL_BYTES:
            raise TransferError("model archive too large when extracted")
        t.extractall(hub, members=members, filter="data")  # rejects absolute paths, .. and links leaving hub


def fetch_model(payload: dict, dest: Path) -> Path | None:
    """Returns the hub cache directory, or None when the dispatch carries no model. Downloads at most once per
    cache lifetime. Raises TransferError (never containing a URL) on size, sha256 or archive problems."""
    m = payload.get("model")
    if not m:
        return None
    dest = Path(dest)
    hub = dest / "hub"
    marker = dest / f"{MARKER_PREFIX}{m['sha256']}"
    if marker.exists() and hub.is_dir():
        return hub
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    tar_path = download(m["url"], dest / "model.tar", min(int(m["size"]), MAX_MODEL_BYTES))
    try:
        if tar_path.stat().st_size != int(m["size"]) or not hmac.compare_digest(sha256_file(tar_path), m["sha256"]):
            raise TransferError("model sha256 mismatch")
        _extract(tar_path, hub)
    except (tarfile.TarError, OSError):
        shutil.rmtree(dest, ignore_errors=True)
        raise TransferError("model archive unreadable") from None
    except TransferError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    tar_path.unlink()
    marker.write_text(m["revision"])
    return hub
