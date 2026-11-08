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
