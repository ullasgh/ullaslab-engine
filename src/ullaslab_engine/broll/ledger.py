"""assets.json + assets.md for an item. One entry per fetched clip."""
from __future__ import annotations
import hashlib
import json
from datetime import date
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_ledger(out: Path, entries: list[dict], meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "assets.json").write_text(json.dumps({**meta, "assets": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Asset ledger", ""]
    for k, v in meta.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "| File | Scene | Source | Creator | Licence | Downloaded | Footage | sha256 |", "|---|---|---|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "/").replace("\n", " ")
    for e in entries:
        lic = f"[{esc(e['licence']['name'])}]({e['licence']['url']})" if e["licence"].get("url") else esc(e["licence"]["name"])
        lines.append(f"| {esc(e['filename'])} | {esc(e['scene'])} | {e['source_url']} | {esc(e['creator'])} | {lic} | "
                     f"{e['download_date']} | {'illustrative' if e['illustrative'] else 'actual'} | `{e['sha256'][:16]}` |")
    notes = [e for e in entries if e["licence"].get("attribution") or e["licence"].get("notice")]
    if notes:
        lines += ["", "## Credits and notices", ""]
        for e in notes:
            txt = "; ".join(x for x in (e["licence"].get("attribution"), e["licence"].get("notice")) if x)
            lines.append(f"- {e['filename']}: {txt}")
    (out / "assets.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
