"""Concrete B-roll providers: Pixabay (primary), NASA, Wikimedia Commons, manual import, Pexels (key-gated), AI stub."""
from __future__ import annotations
import html
import re
from datetime import date
from pathlib import Path

import yaml

from .base import (BrollError, BrollProvider, Candidate, LicenceRecord, LicenceRejected, ProviderDisabled,
                   keep_candidate, probe, tokens)

# ---------------------------------------------------------------- Pixabay
PIXABAY_LICENCE = ("Pixabay Content License", "https://pixabay.com/service/license-summary/")


class PixabayProvider(BrollProvider):
    name = "pixabay"
    needs_key = True
    URL = "https://pixabay.com/api/videos/"

    def __init__(self, *a, api_key: str = "", **kw):
        super().__init__(*a, **kw)
        self.api_key = api_key

    def search(self, query, orientation="landscape", min_res=1080, duration=(0.0, 600.0)):
        if not self.api_key:
            raise ProviderDisabled("pixabay: PIXABAY_API_KEY not set")
        data = self.http.get_json(self.name, self.URL, params={
            "key": self.api_key, "q": query[:100], "video_type": "film", "per_page": 20, "safesearch": "true"})
        out = []
        for h in data.get("hits", []):
            best = None
            for size in ("large", "medium", "small", "tiny"):
                v = (h.get("videos") or {}).get(size) or {}
                if v.get("url") and (best is None or min(v.get("width", 0), v.get("height", 0)) >
                                     min(best.get("width", 0), best.get("height", 0))):
                    best = v
            if not best:
                continue
            c = Candidate(provider=self.name, id=str(h["id"]), title=h.get("tags", ""), page_url=h.get("pageURL", ""),
                          download_url=best["url"], width=int(best.get("width") or 0), height=int(best.get("height") or 0),
                          duration=float(h.get("duration") or 0), creator=h.get("user", ""),
                          tags=[t.strip() for t in h.get("tags", "").split(",") if t.strip()],
                          thumb_url=h.get("picture_id", ""))
            c.licence = self.licence(c)
            if keep_candidate(c, orientation, min_res, duration):
                out.append(c)
        return out

    def fetch(self, c):
        return self._fetch_url(c)

    def licence(self, c):
        return LicenceRecord(name=PIXABAY_LICENCE[0], url=PIXABAY_LICENCE[1], creator=c.creator, source_url=c.page_url,
                             attribution=f"Video by {c.creator} from Pixabay" if c.creator else "Video from Pixabay")


# ---------------------------------------------------------------- Pexels (key-gated, off by default)
class PexelsProvider(BrollProvider):
    name = "pexels"
    needs_key = True
    default_enabled = False
    URL = "https://api.pexels.com/videos/search"

    def __init__(self, *a, api_key: str = "", **kw):
        super().__init__(*a, **kw)
        self.api_key = api_key

    def search(self, query, orientation="landscape", min_res=1080, duration=(0.0, 600.0)):
        if not self.api_key:
            raise ProviderDisabled("pexels: PEXELS_API_KEY not set (key issuance paused); provider stays off")
        data = self.http.get_json(self.name, self.URL, headers={"Authorization": self.api_key},
                                  params={"query": query[:100], "orientation": orientation, "size": "large", "per_page": 20})
        out = []
        for v in data.get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("link") and (f.get("file_type") or "video/mp4") == "video/mp4"]
            if not files:
                continue
            f = max(files, key=lambda f: min(f.get("width") or 0, f.get("height") or 0))
            user = v.get("user") or {}
            c = Candidate(provider=self.name, id=str(v["id"]), title=v.get("url", "").rstrip("/").rsplit("/", 1)[-1].replace("-", " "),
                          page_url=v.get("url", ""), download_url=f["link"], width=int(f.get("width") or 0),
                          height=int(f.get("height") or 0), duration=float(v.get("duration") or 0),
                          creator=user.get("name", ""), extra={"creator_url": user.get("url", "")})
            c.licence = self.licence(c)
            if keep_candidate(c, orientation, min_res, duration):
                out.append(c)
        return out

    def fetch(self, c):
        return self._fetch_url(c)   # file links are public CDN urls: no auth header sent

    def licence(self, c):
        who = f"{c.creator} / " if c.creator else ""
        return LicenceRecord(name="Pexels License", url="https://www.pexels.com/license/", creator=c.creator,
                             source_url=c.page_url, credit_required=True,
                             attribution=f"Video by {who}Pexels. Provided by Pexels",
                             notice="Provided by Pexels. No negative or endorsing depiction of identifiable people; no resale of unmodified clips.")


# ---------------------------------------------------------------- NASA
NASA_BAD = re.compile(r"\b(insignia|logo|emblem|patch|meatball|worm|seal|badge)\b", re.I)


class NasaProvider(BrollProvider):
    name = "nasa"
    URL = "https://images-api.nasa.gov/search"

    def search(self, query, orientation="landscape", min_res=1080, duration=(0.0, 600.0)):
        data = self.http.get_json(self.name, self.URL, params={"q": query[:100], "media_type": "video", "page_size": 20})
        out = []
        for item in (data.get("collection") or {}).get("items", []):
            d = (item.get("data") or [{}])[0]
            if d.get("media_type") != "video" or not item.get("href"):
                continue
            blob = " ".join([d.get("title", ""), d.get("description", ""), " ".join(d.get("keywords") or [])])
            if NASA_BAD.search(blob):
                continue   # metadata says the asset shows the NASA insignia/logo
            nid = d.get("nasa_id", "")
            creator = d.get("photographer") or d.get("secondary_creator") or d.get("center") or "NASA"
            c = Candidate(provider=self.name, id=nid, title=d.get("title", ""),
                          page_url=f"https://images.nasa.gov/details/{nid}", creator=creator,
                          tags=list(d.get("keywords") or []), extra={"collection": item["href"], "date_created": d.get("date_created", "")})
            c.licence = self.licence(c)
            out.append(c)   # resolution unknown until the collection is resolved; checked after fetch
        return out

    def _resolve(self, c: Candidate):
        if c.download_url:
            return
        files = self.http.get_json(self.name, c.extra["collection"])
        mp4 = [u for u in files if isinstance(u, str) and u.lower().endswith(".mp4")]
        # ~orig is often hundreds of MB to GB: prefer ~large (HD proxy), then ~medium; orig only if nothing else
        rank = {"~large": 0, "~medium": 1, "~small": 2, "~mobile": 3, "~preview": 4, "~orig": 5}

        def r(u):
            return next((v for k, v in rank.items() if k in u), 6)
        if not mp4:
            raise BrollError(f"nasa:{c.id}: no mp4 rendition")
        c.download_url = sorted(mp4, key=r)[0].replace("http://", "https://")

    def fetch(self, c):
        self._resolve(c)
        p = self._fetch_url(c)
        info = probe(p)
        c.width, c.height, c.duration = info.get("width", 0), info.get("height", 0), info.get("duration", 0.0)
        return p

    def licence(self, c):
        return LicenceRecord(name="NASA media usage guidelines (public domain)",
                             url="https://www.nasa.gov/nasa-brand-center/images-and-media/", creator=c.creator,
                             source_url=c.page_url, attribution="NASA",
                             notice="NASA, no endorsement. NASA does not endorse this channel or its content. Insignia/logo assets excluded.")


# ---------------------------------------------------------------- Wikimedia Commons
def classify_commons_licence(short: str, usage_terms: str = "", copyrighted: str = "") -> str | None:
    """Return 'PD' | 'CC0' | 'CC-BY' for acceptable licences, None for anything else (SA/NC/ND/unclear)."""
    s = f"{short} {usage_terms}".strip().lower().replace("_", "-")
    if not s:
        return None
    if re.search(r"\b(sa|nc|nd)\b|share-?alike|non-?commercial|no-?deriv|gfdl|fair use|gpl|copyrighted", s):
        return None
    if re.search(r"-sa\b|-nc\b|-nd\b", s):
        return None
    if re.fullmatch(r"(cc0|cc-zero)(\s*1\.0)?|.*\bcc0\b.*", s) or "cc-zero" in s:
        return "CC0"
    if "public domain" in s or re.match(r"^(pd\b|pd-)", s) or s.startswith("public-domain"):
        return "PD"
    if re.match(r"^cc-by(-\d(\.\d)?)?(\s+\d(\.\d)?)?(\s+[a-z]{2,3})?$", s) or re.match(r"^cc by \d", s.replace("-", " ")):
        return "CC-BY"
    return None


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


class WikimediaCommonsProvider(BrollProvider):
    name = "wikimedia"
    URL = "https://commons.wikimedia.org/w/api.php"
    VIDEO_MIME = {"video/webm", "video/ogg", "video/mp4"}

    def search(self, query, orientation="landscape", min_res=1080, duration=(0.0, 600.0)):
        data = self.http.get_json(self.name, self.URL, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query[:100]} filetype:video",
            "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata|mediatype", "formatversion": 2})
        out = []
        for page in (data.get("query") or {}).get("pages", []):
            ii = (page.get("imageinfo") or [None])[0]
            if not ii or ii.get("mime") not in self.VIDEO_MIME:
                continue
            md = ii.get("extmetadata") or {}
            val = lambda k: (md.get(k) or {}).get("value", "")
            kind = classify_commons_licence(val("LicenseShortName"), val("UsageTerms"), val("Copyrighted"))
            if not kind:
                continue
            artist = _strip_html(val("Artist"))
            if kind == "CC-BY" and not artist:
                continue   # attribution would be incomplete
            c = Candidate(provider=self.name, id=str(page.get("pageid")), title=page.get("title", "").removeprefix("File:"),
                          page_url=ii.get("descriptionurl", ""), download_url=ii.get("url", ""),
                          width=int(ii.get("width") or 0), height=int(ii.get("height") or 0),
                          duration=float(ii.get("duration") or 0), creator=artist or "Unknown (public domain)",
                          tags=[_strip_html(val("ImageDescription"))[:200]],
                          extra={"licence_short": val("LicenseShortName"), "licence_kind": kind,
                                 "licence_url": val("LicenseUrl"), "credit": _strip_html(val("Credit")),
                                 "attribution_required": val("AttributionRequired")})
            c.licence = self.licence(c)
            if keep_candidate(c, orientation, min_res, duration):
                out.append(c)
        return out

    def fetch(self, c):
        p = self._fetch_url(c)
        if not (c.width and c.height):
            info = probe(p)
            c.width, c.height = info.get("width", 0), info.get("height", 0)
        return p

    def licence(self, c):
        short = c.extra.get("licence_short", "")
        if c.extra.get("licence_kind") not in ("PD", "CC0", "CC-BY"):
            raise LicenceRejected(f"wikimedia:{c.id}: unclear or non-permitted licence {short!r}")
        kind = c.extra["licence_kind"]
        url = c.extra.get("licence_url") or "https://commons.wikimedia.org/wiki/Commons:Licensing"
        by = kind == "CC-BY"
        return LicenceRecord(name=short, url=url, creator=c.creator, source_url=c.page_url, credit_required=by,
                             attribution=f'"{c.title}" by {c.creator}, {short}, via Wikimedia Commons' if by else "")


# ---------------------------------------------------------------- Manual import
REQUIRED_SIDECAR = ("source_url", "creator", "licence", "download_date")
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
BAD_MANUAL_LICENCE = re.compile(r"\b(nc|nd|sa|non-?commercial|no-?deriv|share-?alike)\b", re.I)


def sidecar_for(clip: Path) -> Path | None:
    for ext in (".yaml", ".yml"):
        p = clip.with_suffix(ext)
        if p.is_file():
            return p
    return None


def validate_sidecar(clip: Path) -> tuple[dict | None, str]:
    sc = sidecar_for(clip)
    if not sc:
        return None, "missing sidecar yaml"
    try:
        d = yaml.safe_load(sc.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None, "sidecar is not valid yaml"
    if not isinstance(d, dict):
        return None, "sidecar is not a mapping"
    missing = [k for k in REQUIRED_SIDECAR if not str(d.get(k) or "").strip()]
    if missing:
        return None, "sidecar missing: " + ", ".join(missing)
    if not str(d["source_url"]).startswith(("http://", "https://")):
        return None, "source_url must be an http(s) URL"
    if BAD_MANUAL_LICENCE.search(str(d["licence"])):
        return None, f"licence {d['licence']!r} not permitted (SA/NC/ND)"
    return d, ""


class ManualImportProvider(BrollProvider):
    name = "manual"

    def __init__(self, *a, inbox: Path | None = None, **kw):
        super().__init__(*a, **kw)
        self.inbox = Path(inbox) if inbox else Path("footage/inbox")
        self.rejected: list[tuple[str, str]] = []

    def search(self, query, orientation="landscape", min_res=1080, duration=(0.0, 600.0)):
        self.rejected = []
        q = tokens(query)
        out = []
        for clip in sorted(self.inbox.glob("*")) if self.inbox.is_dir() else []:
            if clip.suffix.lower() not in VIDEO_EXT:
                continue
            d, why = validate_sidecar(clip)
            if d is None:
                self.rejected.append((clip.name, why))
                continue
            info = probe(clip)
            tags = [str(t) for t in (d.get("tags") or [])]
            c = Candidate(provider=self.name, id=clip.name, title=str(d.get("title") or clip.stem.replace("_", " ").replace("-", " ")),
                          page_url=str(d["source_url"]), creator=str(d["creator"]), tags=tags,
                          width=info.get("width", 0), height=info.get("height", 0), duration=info.get("duration", 0.0),
                          local_path=str(clip), extra={"sidecar": d})
            c.licence = self.licence(c)
            if q and not (q & tokens(c.text())):
                continue
            if keep_candidate(c, orientation, min_res, duration):
                out.append(c)
        return out

    def fetch(self, c):
        p = Path(c.local_path)
        if not p.is_file():
            raise BrollError(f"manual:{c.id}: file missing")
        return p

    def licence(self, c):
        d = c.extra.get("sidecar") or validate_sidecar(Path(c.local_path))[0]
        if not d:
            raise LicenceRejected(f"manual:{c.id}: incomplete sidecar")
        name = str(d["licence"])
        pex = "pexels" in name.lower() or "pexels.com" in str(d["source_url"]).lower()
        note = "Provided by Pexels" if pex else ""
        return LicenceRecord(name=name, url=str(d.get("licence_url") or ""), creator=str(d["creator"]),
                             source_url=str(d["source_url"]), credit_required=pex, attribution=note, notice=str(d.get("notes") or ""))


# ---------------------------------------------------------------- AI (hard-disabled)
_AI_MSG = "AI B-roll is disabled: needs WP9 research plus explicit owner approval"


class AIProviderDisabled(ProviderDisabled):
    pass


class AIProvider(BrollProvider):
    """AI-generated B-roll. HARD-DISABLED: every method raises.

    Gated on the WP9 research (docs/research/ai-broll.md: Kaggle terms/AUP, YouTube/IG rules, model licences)
    AND explicit owner approval. Not wired into the registry; the registry refuses to enable it."""
    name = "ai"
    default_enabled = False

    def __init__(self, *a, **kw):
        raise AIProviderDisabled(_AI_MSG)

    def search(self, *a, **kw):
        raise AIProviderDisabled(_AI_MSG)

    def fetch(self, *a, **kw):
        raise AIProviderDisabled(_AI_MSG)

    def licence(self, *a, **kw):
        raise AIProviderDisabled(_AI_MSG)
