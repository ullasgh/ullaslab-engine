import http.server
import io as pyio
import json
import threading
import zipfile
import pytest
from ullaslab_engine import io as eio
from ullaslab_engine import cli

GOOD = "https://acct.r2.cloudflarestorage.com/bkt/key.zip?X-Amz-Signature=abc123&X-Amz-Expires=7200"


def payload(**kw):
    p = {"job_id": "j-1", "bundle_url": GOOD, "languages": ["en", "hi", "ta", "ar"],
         "outputs": {"master.mp4": GOOD + "&n=1", "qa_en.json": GOOD + "&n=2"}}
    p.update(kw)
    return p


def test_valid_payload_passes():
    assert eio.validate_payload(payload())


@pytest.mark.parametrize("bad", [
    payload(bundle_url="https://evil.example.com/x"),
    payload(bundle_url="http://acct.r2.cloudflarestorage.com/x"),
    payload(outputs={"master.mp4": "https://evil.example.com/p"}),
    payload(outputs={"../x": GOOD}),
    payload(job_id="a b"),
    payload(languages=["english"]),
    payload(voice_url="https://169.254.169.254/latest"),
])
def test_payload_rejected(bad):
    with pytest.raises(eio.TransferError) as e:
        eio.validate_payload(bad)
    assert "evil" not in str(e.value) and "169" not in str(e.value)  # errors never echo values


def test_missing_fields():
    with pytest.raises(eio.TransferError):
        eio.validate_payload({"job_id": "x"})


def test_mask_lines_cover_url_query_and_path():
    lines = eio.mask_lines(payload(voice_url=GOOD + "&v=1"))
    joined = "\n".join(lines)
    assert all(l.startswith("::add-mask::") for l in lines)
    assert GOOD in joined and "X-Amz-Signature=abc123" in joined and "bkt/key.zip" in joined
    assert len(lines) >= 4


def test_safe_unzip_blocks_traversal_and_bombs(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(eio.TransferError):
        eio.safe_unzip(z, tmp_path / "out")
    z2 = tmp_path / "b.zip"
    with zipfile.ZipFile(z2, "w") as f:
        f.writestr("ok/a.txt", "x")
    eio.safe_unzip(z2, tmp_path / "out2")
    assert (tmp_path / "out2" / "ok" / "a.txt").exists()


class H(http.server.BaseHTTPRequestHandler):
    store = {}

    def do_GET(self):
        body = self.store.get(self.path)
        self.send_response(200 if body is not None else 404); self.end_headers()
        if body is not None:
            self.wfile.write(body)

    def do_PUT(self):
        self.store[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200); self.end_headers()

    def log_message(self, *a): pass


def test_download_upload_roundtrip_and_error_redaction(tmp_path, monkeypatch):
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setenv("ULLASLAB_ALLOWED_HOSTS", "127.0.0.1")
    f = tmp_path / "a.txt"; f.write_text("hello")
    eio.upload(base + "/k?sig=SECRETSIG", f)
    assert eio.download(base + "/k?sig=SECRETSIG", tmp_path / "b.txt").read_text() == "hello"
    with pytest.raises(eio.TransferError) as e:
        eio.download(base + "/missing?sig=SECRETSIG", tmp_path / "c.txt")
    assert "SECRETSIG" not in str(e.value) and "127.0.0.1" not in str(e.value)
    srv.shutdown()


def test_cli_plan_outputs_matrix_without_urls(tmp_path, capsys):
    f = tmp_path / "event.json"
    f.write_text(json.dumps({"action": "render", "client_payload": payload()}))
    assert cli.main(["plan", "--payload", str(f)]) == 0
    out = capsys.readouterr().out
    assert "r2.cloudflarestorage" not in out and "Signature" not in out
    matrix = json.loads(out.splitlines()[0].split("=", 1)[1])
    langs = {r["lang"]: r["extras"] for r in matrix["include"]}
    assert set(langs) == {"hi", "ta", "ar"}            # en is the master, not a dub
    assert langs["ta"] == "parler" and langs["ar"] == "chatterbox"
    assert langs["hi"] == "chatterbox"                  # parler dropped: conflicting pins
    assert "has_dubs=true" in out and "master_extras=chatterbox,kokoro" in out


def test_cli_rejects_bad_payload(tmp_path, capsys):
    f = tmp_path / "e.json"
    f.write_text(json.dumps({"client_payload": payload(bundle_url="https://evil.example.com/x")}))
    assert cli.main(["plan", "--payload", str(f)]) == 2
    assert "evil" not in capsys.readouterr().err


def test_voice_clip_urls_validated_and_masked():
    clips = {"1": GOOD + "&c=1", "2": GOOD + "&c=2"}
    eio.validate_payload(payload(voice_clip_urls=clips))
    assert any("c=2" in l for l in eio.mask_lines(payload(voice_clip_urls=clips)))
    for bad in ({"1": "https://169.254.169.254/x"}, {"9": GOOD}, ["x"]):
        with pytest.raises(eio.TransferError):
            eio.validate_payload(payload(voice_clip_urls=bad))


# --- WP12: Parler weights from the private mirror ----------------------------------------------

import hashlib  # noqa: E402
import tarfile  # noqa: E402
from ullaslab_engine import model as emodel  # noqa: E402

REV = "a" * 40


def make_archive(path, evil=False):
    src = path.parent / "src"
    snap = src / "models--ai4bharat--indic-parler-tts" / "snapshots" / REV
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    (src / "models--ai4bharat--indic-parler-tts" / "refs").mkdir()
    (src / "models--ai4bharat--indic-parler-tts" / "refs" / "main").write_text(REV)
    with tarfile.open(path, "w") as t:
        t.add(src / "models--ai4bharat--indic-parler-tts", arcname="models--ai4bharat--indic-parler-tts")
        if evil:
            (src / "x").write_text("x")
            t.add(src / "x", arcname="../escape.txt")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_obj(tar, sha, url="http://127.0.0.1:1/m.tar"):
    return {"url": url, "sha256": sha, "revision": REV, "size": tar.stat().st_size}


def serve_file(tmp_path, name, hits):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            data = (tmp_path / name).read_bytes()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def local_hosts(monkeypatch):
    monkeypatch.setenv("ULLASLAB_ALLOWED_HOSTS", "127.0.0.1")


def test_model_payload_validated_and_masked():
    good = {"url": GOOD + "&m=1", "sha256": "b" * 64, "revision": REV, "size": 10}
    assert eio.validate_payload(payload(model=good))
    assert "&m=1" in "\n".join(eio.mask_lines(payload(model=good)))
    for bad in ({**good, "url": "https://evil.example.com/m"}, {**good, "sha256": "zz"}, {**good, "size": 10**12},
                {**good, "extra": 1}, {**good, "revision": "main"}, "x"):
        with pytest.raises(eio.TransferError) as e:
            eio.validate_payload(payload(model=bad))
        assert "evil" not in str(e.value)


def test_fetch_model_verifies_extracts_and_marks(tmp_path, local_hosts):
    tar = tmp_path / "m.tar"
    sha = make_archive(tar)
    hits = []
    srv = serve_file(tmp_path, "m.tar", hits)
    url = f"http://127.0.0.1:{srv.server_address[1]}/m.tar?sig=SECRETSIG"
    p = {"model": model_obj(tar, sha, url)}
    dest = tmp_path / "cache"
    hub = emodel.fetch_model(p, dest)
    assert (hub / "models--ai4bharat--indic-parler-tts/refs/main").read_text() == REV
    assert (hub / "models--ai4bharat--indic-parler-tts/snapshots" / REV / "config.json").exists()
    from ullaslab_engine.tts.parler_engine import MODEL
    assert (hub / ("models--" + MODEL.replace("/", "--")) / "refs/main").exists()  # the name the engine loads offline
    assert not (dest / "model.tar").exists() and (dest / f".ok-{sha}").exists()
    assert emodel.fetch_model(p, dest) == hub and len(hits) == 1  # cache restored: no second download
    srv.shutdown()


def test_fetch_model_sha_mismatch_fails_and_cleans(tmp_path, local_hosts):
    tar = tmp_path / "m.tar"
    make_archive(tar)
    hits = []
    srv = serve_file(tmp_path, "m.tar", hits)
    url = f"http://127.0.0.1:{srv.server_address[1]}/m.tar?sig=SECRETSIG"
    dest = tmp_path / "cache"
    with pytest.raises(eio.TransferError) as e:
        emodel.fetch_model({"model": model_obj(tar, "0" * 64, url)}, dest)
    assert "sha256" in str(e.value) and "SECRETSIG" not in str(e.value) and "127.0.0.1" not in str(e.value)
    assert not dest.exists()
    srv.shutdown()


def test_fetch_model_rejects_traversal_archive(tmp_path, local_hosts):
    tar = tmp_path / "m.tar"
    sha = make_archive(tar, evil=True)
    srv = serve_file(tmp_path, "m.tar", [])
    url = f"http://127.0.0.1:{srv.server_address[1]}/m.tar"
    with pytest.raises(eio.TransferError):
        emodel.fetch_model({"model": model_obj(tar, sha, url)}, tmp_path / "cache")
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "cache").exists()
    srv.shutdown()


def test_fetch_model_cli_without_model_prints_empty_hub(tmp_path, capsys):
    f = tmp_path / "e.json"
    f.write_text(json.dumps({"client_payload": payload()}))
    assert cli.main(["fetch-model", "--payload", str(f), "--dest", str(tmp_path / "c")]) == 0
    assert capsys.readouterr().out.strip() == "hub="
