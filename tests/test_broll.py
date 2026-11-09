import json
import subprocess
from pathlib import Path

import pytest
import yaml

from ullaslab_engine.broll import (AIProvider, AIProviderDisabled, BrollError, BudgetExceeded, Http, LicenceRejected,
                                   ManualImportProvider, NasaProvider, PexelsProvider, PixabayProvider, ProviderDisabled,
                                   WikimediaCommonsProvider)
from ullaslab_engine.broll.history import History
from ullaslab_engine.broll.providers import classify_commons_licence
from ullaslab_engine.broll.rank import FallbackRanker
from ullaslab_engine.broll.registry import build_providers, load_config
from ullaslab_engine.broll.run import run_fetch
from ullaslab_engine.broll.scenes import load_scenes


class Resp:
    def __init__(self, status=200, data=None, body=b"", headers=None):
        self.status_code, self._data, self.body, self.headers = status, data, body, headers or {}

    def json(self):
        return self._data

    def iter_content(self, n):
        yield self.body

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        self.calls.append((url, params))
        r = self.routes[url]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        return r


def mkhttp(tmp_path, routes, **kw):
    s = FakeSession(routes)
    sleeps = []
    return Http(tmp_path / "cache", session=s, sleep=sleeps.append, **kw), s, sleeps


def make_video(path: Path, w=640, h=360, secs=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=10:duration={secs}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


PIX = {"hits": [{"id": 7, "pageURL": "https://pixabay.com/videos/x-7/", "tags": "container ship, port, cargo", "duration": 12,
                 "user": "bob", "videos": {"large": {"url": "https://cdn/p7_l.mp4", "width": 1920, "height": 1080},
                                             "tiny": {"url": "https://cdn/p7_t.mp4", "width": 640, "height": 360}}},
                {"id": 8, "pageURL": "https://pixabay.com/videos/y-8/", "tags": "portrait", "duration": 9, "user": "al",
                 "videos": {"large": {"url": "https://cdn/p8.mp4", "width": 1080, "height": 1920}}}]}


def test_pixabay_search_orientation_licence_and_secret_scrub(tmp_path):
    http, s, _ = mkhttp(tmp_path, {PixabayProvider.URL: Resp(data=PIX)})
    p = PixabayProvider(http=http, api_key="SECRETKEY")
    out = p.search("container ship", "landscape", 1080, (3, 60))
    assert [c.id for c in out] == ["7"] and out[0].width == 1920   # picks largest rendition, drops portrait
    assert out[0].licence.name == "Pixabay Content License"
    assert not any("SECRETKEY" in f.name or "SECRETKEY" in f.read_text() for f in (tmp_path / "cache" / "meta").iterdir())
    assert [c.id for c in p.search("x", "portrait", 1080, (3, 60))] == ["8"]


def test_pixabay_without_key_raises_disabled(tmp_path):
    http, _, _ = mkhttp(tmp_path, {})
    with pytest.raises(ProviderDisabled):
        PixabayProvider(http=http).search("x")


def test_cache_hit_metadata_and_download(tmp_path):
    http, s, _ = mkhttp(tmp_path, {PixabayProvider.URL: Resp(data=PIX), "https://cdn/p7_l.mp4": Resp(body=b"VIDEO")})
    p = PixabayProvider(http=http, api_key="k")
    c = p.search("ship", "landscape", 1080, (3, 60))[0]
    p.search("ship", "landscape", 1080, (3, 60))
    f1 = p.fetch(c)
    f2 = p.fetch(c)
    assert f1 == f2 and f1.read_bytes() == b"VIDEO"
    assert len(s.calls) == 2   # one search, one download
    assert http.cache_hits == 2


def test_retry_bounds_and_backoff(tmp_path):
    http, s, sleeps = mkhttp(tmp_path, {"https://u/": [Resp(429), Resp(503), Resp(200, data={"ok": 1})]}, retries=3, backoff=1.0)
    assert http.get_json("t", "https://u/") == {"ok": 1}
    assert sleeps == [1.0, 2.0]
    http, s, sleeps = mkhttp(tmp_path / "b", {"https://u/": Resp(500)}, retries=2)
    with pytest.raises(BrollError, match="giving up"):
        http.get_json("t", "https://u/")
    assert len(s.calls) == 3   # 1 + 2 retries, then stop


def test_client_error_not_retried_and_budget(tmp_path):
    http, s, _ = mkhttp(tmp_path, {"https://u/": Resp(404)})
    with pytest.raises(BrollError, match="404"):
        http.get_json("t", "https://u/")
    assert len(s.calls) == 1
    http, s, _ = mkhttp(tmp_path / "c", {"https://u/": Resp(500)}, total_budget=2, retries=5)
    with pytest.raises(BudgetExceeded):
        http.get_json("t", "https://u/")
    assert len(s.calls) == 2
    http, s, _ = mkhttp(tmp_path / "d", {"https://u/": Resp(data={})})
    http.configure("t", max_requests=1)
    http.get_json("t", "https://u/", params={"a": 1})
    with pytest.raises(BudgetExceeded):
        http.get_json("t", "https://u/", params={"a": 2})


def test_rate_limit_spacing(tmp_path):
    t = [0.0]
    s = FakeSession({"https://u/": Resp(data={})})
    sleeps = []
    http = Http(tmp_path, session=s, sleep=sleeps.append, clock=lambda: t[0])
    http.configure("t", min_interval_s=1.0)
    http.get_json("t", "https://u/", params={"a": 1})
    http.get_json("t", "https://u/", params={"a": 2})
    assert sleeps == [1.0]


NASA_SEARCH = {"collection": {"items": [
    {"href": "https://c/a.json", "data": [{"nasa_id": "A1", "title": "Container ship seen from ISS", "media_type": "video",
                                           "keywords": ["ship"], "center": "JSC", "date_created": "2020-01-01"}]},
    {"href": "https://c/b.json", "data": [{"nasa_id": "B1", "title": "NASA logo animation", "media_type": "video", "keywords": []}]},
    {"href": "https://c/c.json", "data": [{"nasa_id": "C1", "title": "Patch", "description": "mission insignia", "media_type": "video"}]}]}}


def test_nasa_excludes_logos_and_records_no_endorsement(tmp_path):
    http, s, _ = mkhttp(tmp_path, {NasaProvider.URL: Resp(data=NASA_SEARCH), "https://c/a.json":
                                   Resp(data=["http://x/a~orig.mp4", "http://x/a~large.mp4", "http://x/a.srt"])})
    p = NasaProvider(http=http)
    out = p.search("ship")
    assert [c.id for c in out] == ["A1"]
    assert "no endorsement" in out[0].licence.notice and out[0].licence.attribution == "NASA"
    p._resolve(out[0])
    assert out[0].download_url == "https://x/a~large.mp4"


def commons_page(pid, title, short, w=1920, h=1080, artist="Jane", mime="video/webm", terms=""):
    return {"pageid": pid, "title": "File:" + title, "imageinfo": [{"url": f"https://upload/{pid}.webm", "descriptionurl": f"https://commons/{pid}",
            "width": w, "height": h, "duration": 20, "mime": mime, "extmetadata": {
                "LicenseShortName": {"value": short}, "UsageTerms": {"value": terms or short}, "LicenseUrl": {"value": "https://cc/by"},
                "Artist": {"value": f'<a href="x">{artist}</a>' if artist else ""}, "ImageDescription": {"value": "ship"}}}]}


@pytest.mark.parametrize("short,expected", [
    ("Public domain", "PD"), ("PD-USGov-NASA", "PD"), ("CC0", "CC0"), ("CC-BY 4.0", "CC-BY"), ("CC BY 3.0", "CC-BY"),
    ("CC BY-SA 4.0", None), ("CC-BY-SA-3.0", None), ("CC BY-NC 2.0", None), ("CC BY-ND 4.0", None), ("GFDL", None),
    ("", None), ("Attribution unclear", None), ("Fair use", None)])
def test_commons_licence_classifier(short, expected):
    assert classify_commons_licence(short) == expected


def test_wikimedia_filters_and_records_attribution(tmp_path):
    pages = [commons_page(1, "ok.webm", "CC BY 4.0"), commons_page(2, "sa.webm", "CC BY-SA 4.0"), commons_page(3, "nc.webm", "CC BY-NC 4.0"),
             commons_page(4, "pd.webm", "Public domain", artist=""), commons_page(5, "unclear.webm", ""),
             commons_page(6, "noartist.webm", "CC BY 4.0", artist=""), commons_page(7, "img.jpg", "CC0", mime="image/jpeg"),
             commons_page(8, "cc0.webm", "CC0")]
    http, _, _ = mkhttp(tmp_path, {WikimediaCommonsProvider.URL: Resp(data={"query": {"pages": pages}})})
    out = WikimediaCommonsProvider(http=http).search("ship")
    assert sorted(c.id for c in out) == ["1", "4", "8"]
    cc = next(c for c in out if c.id == "1")
    assert cc.licence.name == "CC BY 4.0" and cc.licence.credit_required and "Jane" in cc.licence.attribution and cc.licence.url
    with pytest.raises(LicenceRejected):
        c = next(c for c in out if c.id == "1")
        c.extra["licence_kind"] = "SA"
        WikimediaCommonsProvider(http=http).licence(c)


def write_clip(inbox, name, sidecar=None):
    inbox.mkdir(parents=True, exist_ok=True)
    make_video(inbox / f"{name}.mp4")
    if sidecar is not None:
        (inbox / f"{name}.yaml").write_text(yaml.safe_dump(sidecar))


GOOD = {"source_url": "https://www.pexels.com/video/123/", "creator": "Sam", "licence": "Pexels License",
        "download_date": "2026-11-09", "tags": ["container ship", "port"]}


def test_manual_import_validation(tmp_path):
    inbox = tmp_path / "inbox"
    write_clip(inbox, "ship_port", GOOD)
    write_clip(inbox, "nosidecar")
    write_clip(inbox, "incomplete", {**GOOD, "creator": ""})
    write_clip(inbox, "nc", {**GOOD, "licence": "CC BY-NC 4.0"})
    write_clip(inbox, "badurl", {**GOOD, "source_url": "file:///x"})
    p = ManualImportProvider(inbox=inbox)
    out = p.search("container ship", "landscape", 360, (1, 60))
    assert [c.id for c in out] == ["ship_port.mp4"]
    assert dict(p.rejected).keys() == {"nosidecar.mp4", "incomplete.mp4", "nc.mp4", "badurl.mp4"}
    assert "creator" in dict(p.rejected)["incomplete.mp4"]
    lic = out[0].licence
    assert lic.credit_required and lic.attribution == "Provided by Pexels" and lic.source_url == GOOD["source_url"]
    assert p.fetch(out[0]).name == "ship_port.mp4"


def test_pexels_gated_and_credit(tmp_path):
    http, _, _ = mkhttp(tmp_path, {PexelsProvider.URL: Resp(data={"videos": [{"id": 1, "url": "https://www.pexels.com/video/a-ship-1/", "duration": 10,
        "user": {"name": "Ann", "url": "u"}, "video_files": [{"link": "https://v/1.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"}]}]})})
    with pytest.raises(ProviderDisabled):
        PexelsProvider(http=http).search("x")
    out = PexelsProvider(http=http, api_key="k").search("x", "landscape", 1080, (3, 60))
    assert "Provided by Pexels" in out[0].licence.attribution and out[0].licence.credit_required
    cfg = load_config()
    assert next(e for e in cfg["providers"] if e["name"] == "pexels")["enabled"] is False


def test_ai_provider_hard_disabled(tmp_path):
    with pytest.raises(AIProviderDisabled):
        AIProvider()
    with pytest.raises(AIProviderDisabled):
        AIProvider.search(object(), "x")
    cfg = {"providers": [{"name": "ai", "enabled": True}]}
    http, _, _ = mkhttp(tmp_path, {})
    provs, notes = build_providers(cfg, http, env={})
    assert provs == [] and "refused" in notes[0]


def test_registry_order_and_missing_keys(tmp_path):
    http, _, _ = mkhttp(tmp_path, {})
    provs, notes = build_providers(load_config(), http, env={}, root=tmp_path)
    assert [p.name for p in provs] == ["manual", "nasa", "wikimedia"]
    assert any("pixabay: pending-key" in n for n in notes)
    provs, _ = build_providers(load_config(), http, env={"PIXABAY_API_KEY": "k"}, root=tmp_path)
    assert [p.name for p in provs] == ["manual", "pixabay", "nasa", "wikimedia"]
    assert http.limits["pixabay"]["min_interval_s"] > 0


def test_scenes_tolerant(tmp_path):
    f = tmp_path / "scenes.json"
    f.write_text(json.dumps({"scenes": [
        {"id": "s1", "type": "footage", "visual_objective": "ship", "search_terms": ["container ship"], "illustrative": False,
         "narration_span": {"start": 1.0, "end": 6.5}, "extra": 1},
        {"id": "s2", "type": "chart"}, {"search_terms": "oil refinery", "start": 0, "end": 4}]}))
    sc = load_scenes(f)
    assert [s.id for s in sc] == ["s1", "s3"] and sc[0].duration == 5.5 and sc[0].illustrative is False
    assert sc[1].search_terms == ["oil refinery"]


def test_history_blocks_recent(tmp_path):
    h = History(tmp_path / "h.json", recent=2)
    for i in range(3):
        h.record(f"e{i}", [f"pixabay:{i}"])
    assert History(tmp_path / "h.json", recent=2).blocked("e9") == {"pixabay:1", "pixabay:2"}
    assert History(tmp_path / "h.json", recent=2).blocked("e2") == {"pixabay:0", "pixabay:1"}


def test_end_to_end_dedupe_ledger_and_history(tmp_path):
    vid = make_video(tmp_path / "src.mp4", 1920, 1080)
    other = make_video(tmp_path / "src2.mp4", 1920, 1080, secs=3)
    hits = {"hits": [{"id": i, "pageURL": f"https://pixabay.com/videos/{i}/", "tags": "container ship port", "duration": 5, "user": "bob",
                      "videos": {"large": {"url": f"https://cdn/{i}.mp4", "width": 1920, "height": 1080}}} for i in (1, 2)]}
    http, s, _ = mkhttp(tmp_path, {PixabayProvider.URL: Resp(data=hits), "https://cdn/1.mp4": Resp(body=vid.read_bytes()),
                                   "https://cdn/2.mp4": Resp(body=other.read_bytes())})
    scenes = tmp_path / "ep" / "scenes.json"
    scenes.parent.mkdir()
    scenes.write_text(json.dumps([{"id": "a", "type": "footage", "search_terms": ["container ship"], "visual_objective": "container ship at port"},
                                  {"id": "b", "type": "footage", "search_terms": ["container ship"], "visual_objective": "container ship at port", "illustrative": False}]))
    cfgf = tmp_path / "broll.yaml"
    c = load_config()
    c["providers"] = [e for e in c["providers"] if e["name"] == "pixabay"]
    cfgf.write_text(yaml.safe_dump(c))
    out = tmp_path / "out"
    r = run_fetch(scenes, out, channel="ch", config=cfgf, env={"PIXABAY_API_KEY": "k"}, http=http, ranker=FallbackRanker(),
                  history_dir=tmp_path / "hist")
    ents = json.loads((out / "assets.json").read_text())["assets"]
    assert len(ents) == 2 and len({e["sha256"] for e in ents}) == 2     # no clip repeats within the episode
    e = ents[0]
    for k in ("filename", "source_url", "creator", "licence", "download_date", "scene", "illustrative", "sha256"):
        assert k in e
    assert e["licence"]["name"] and e["licence"]["url"] and ents[1]["illustrative"] is False
    assert "Pixabay Content License" in (out / "assets.md").read_text()
    assert (out / "footage" / "a.mp4").exists()
    # next episode: both clips blocked by channel history
    r2 = run_fetch(scenes, tmp_path / "out2", channel="ch", episode="next", config=cfgf, env={"PIXABAY_API_KEY": "k"}, http=http,
                   ranker=FallbackRanker(), history_dir=tmp_path / "hist")
    assert [x["status"] for x in r2["report"]] == ["no-candidate", "no-candidate"]
