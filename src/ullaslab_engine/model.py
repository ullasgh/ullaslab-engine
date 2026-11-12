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
MAIN_REPO = "models--ai4bharat--indic-parler-tts"
WEIGHTS = "model.safetensors"
MIN_WEIGHT_BYTES = 1024**3  # the fp32 weights are about 3.7 GB; an archive of links held none of them (12.8 MB in all)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_real_files(hub: Path, sizes: dict[str, int]) -> None:
    """The extracted cache must hold real files: every archive file present with its archived size, and the config and
    the weights of the main model resolving to regular files (never links) of a plausible size. Public-safe messages."""
    for name, size in sizes.items():
        f = hub / name
        if f.is_symlink() or not f.is_file() or f.stat().st_size != size:
            raise TransferError("model files are missing or have the wrong size after extraction")
    snaps = hub / MAIN_REPO / "snapshots"
    revs = [d for d in snaps.iterdir() if d.is_dir()] if snaps.is_dir() else []
    ok = False
    for snap in revs:
        cfg, w = snap / "config.json", snap / WEIGHTS
        ok = ok or (cfg.is_file() and not cfg.is_symlink() and cfg.stat().st_size > 0
                    and w.is_file() and not w.is_symlink() and w.stat().st_size >= MIN_WEIGHT_BYTES)
    if not ok:
        raise TransferError("model weights are missing or implausibly small in the archive: the owner must rebuild the model mirror")


def _extract(tar_path: Path, hub: Path) -> None:
    hub.mkdir(parents=True)
    total = 0
    sizes: dict[str, int] = {}
    with tarfile.open(tar_path) as t:
        members = t.getmembers()
        for m in members:
            top = Path(m.name).parts[:1]
            if not top or not top[0].startswith("models--") or not (m.isfile() or m.isdir() or m.issym()):
                raise TransferError("model archive has an unexpected entry")
            total += m.size
            if m.isfile():
                sizes[m.name] = m.size
        if total > MAX_MODEL_BYTES:
            raise TransferError("model archive too large when extracted")
        t.extractall(hub, members=members, filter="data")  # rejects absolute paths, .. and links leaving hub
    _check_real_files(hub, sizes)


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
        try:
            _check_real_files(hub, {})  # a restored cache is checked too: an older link-only extraction is not reused
            return hub
        except TransferError:
            pass
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
