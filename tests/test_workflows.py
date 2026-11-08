"""Public-repo hard rules, enforced on the workflow files themselves."""
from pathlib import Path
import re
import yaml
import pytest
from ullaslab_engine.config import ROOT

WF = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def load(p):
    d = yaml.safe_load(p.read_text())
    d["on"] = d.get("on", d.get(True))  # PyYAML parses bare `on` as True
    return d


@pytest.mark.parametrize("p", WF, ids=lambda p: p.name)
def test_permissions_empty_everywhere(p):
    d = load(p)
    assert d["permissions"] == {}
    for name, job in d["jobs"].items():
        assert job.get("permissions", {}) == {}, name


@pytest.mark.parametrize("p", WF, ids=lambda p: p.name)
def test_no_fork_reachable_triggers(p):
    on = load(p)["on"]
    assert not ({"pull_request", "pull_request_target", "issue_comment", "workflow_run"} & set(on))


def test_render_only_repository_dispatch():
    assert set(load(ROOT / ".github/workflows/render.yml")["on"]) == {"repository_dispatch"}


def test_every_render_job_masks_urls_first():
    d = load(ROOT / ".github/workflows/render.yml")
    for name, job in d["jobs"].items():
        assert "add-mask" in job["steps"][0]["run"], name


def test_render_never_uploads_artifacts_or_echoes_payload():
    txt = (ROOT / ".github/workflows/render.yml").read_text()
    assert "upload-artifact" not in txt and "toJson(github.event" not in txt and "toJSON(github.event" not in txt
    assert "cat $GITHUB_EVENT_PATH" not in txt and "set -x" not in txt
    assert "secrets." not in txt


def test_actions_pinned_to_sha():
    for p in WF:
        for m in re.finditer(r"uses:\s*([^\s]+)", p.read_text()):
            assert re.search(r"@[0-9a-f]{40}$", m.group(1)), m.group(1)


def test_matrix_per_language_and_fail_fast_off():
    j = load(ROOT / ".github/workflows/render.yml")["jobs"]["dub"]
    assert j["strategy"]["fail-fast"] is False and "matrix" in j["strategy"]


def test_repo_ignores_media_and_secrets():
    ig = (ROOT / ".gitignore").read_text()
    for pat in (".env", "*.wav", "*.mp4", "*.pem", "out/", "work/"):
        assert pat in ig, pat
