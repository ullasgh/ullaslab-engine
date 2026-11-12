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


def test_render_triggers_are_dispatch_and_the_fixture_proof_run_only():
    on = load(ROOT / ".github/workflows/render.yml")["on"]
    assert set(on) == {"repository_dispatch", "workflow_dispatch"}
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"fixture"} and inputs["fixture"]["type"] == "choice"  # no free-form input reaches a shell


def _steps(job: str) -> list[dict]:
    return load(ROOT / ".github/workflows/render.yml")["jobs"][job]["steps"]


def test_only_secret_is_the_footage_key_on_the_studio_step():
    """WP8: the stock-footage search key (repo secret) reaches the studio render step only; nothing else uses a secret."""
    txt = (ROOT / ".github/workflows/render.yml").read_text()
    assert re.findall(r"secrets\.[A-Za-z_]+", txt) == ["secrets.PIXABAY_API_KEY"]
    holders = [s for s in _steps("master") if "secrets." in str(s.get("env", {}))]
    assert len(holders) == 1 and "studio run" in holders[0]["run"]
    assert set(holders[0]["env"]) == {"PIXABAY_API_KEY", "ULLASLAB_MUSIC_FETCH"} and holders[0]["env"]["ULLASLAB_MUSIC_FETCH"] == "off"
    for p in WF:
        if p.name != "render.yml":
            assert "secrets." not in p.read_text(), p.name


def test_studio_steps_log_privately_and_print_only_for_the_fixture():
    """Script text can appear in voice/studio errors: those steps append to work/logs/studio.log (uploaded by presigned PUT
    as studio_log.txt) and print the log only on the synthetic fixture run."""
    steps = _steps("master")
    runs = [s.get("run", "") for s in steps]
    for cmd in ("studio-voice", "studio run"):
        line = next(l for r in runs for l in r.splitlines() if cmd in l)
        assert ">> work/logs/studio.log 2>&1" in line, cmd
    for r in runs:
        for l in r.splitlines():
            if "work/logs/studio.log" in l and ("tail" in l or "cat " in l):
                assert l.strip().startswith('if [ "$FIXTURE" = true ]'), l
    txt = (ROOT / ".github/workflows/render.yml").read_text()
    # the public log shows which stage failed (stage name + error class only; the failure marker carries no message)
    assert "^\\[failed\\] [a-z]+ [A-Za-z]+$" in txt
    assert "FIXTURE: ${{ github.event_name == 'workflow_dispatch' }}" in txt


def test_fixture_run_fetches_and_uploads_nothing():
    steps = _steps("master")
    for s in steps:
        r = s.get("run", "")
        if "fetch --payload" in r or "upload --payload" in r:
            assert "repository_dispatch" in s["if"], s.get("name")
        if "studio-fixture" in r:
            assert s["if"] == "github.event_name == 'workflow_dispatch'"


def test_render_fits_the_poll_window_and_url_lifetime():
    """Master then dubs must end inside the private repo's 3 h poll window (RENDER_TIMEOUT) and the presigned URL lifetime
    (3 h 15 min, content produce/r2.py DISPATCH_PRESIGN_SECONDS)."""
    j = load(ROOT / ".github/workflows/render.yml")["jobs"]
    assert j["plan"]["timeout-minutes"] + j["master"]["timeout-minutes"] + j["dub"]["timeout-minutes"] <= 180
    assert all(job["runs-on"] == "ubuntu-24.04" for job in j.values())


def test_runners_have_ffmpeg():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "apt-get install" in ci and "ffmpeg" in ci
    assert any("ffmpeg" in s.get("run", "") and "apt-get install" in s.get("run", "") for s in _steps("master"))


def test_every_render_job_masks_urls_first():
    d = load(ROOT / ".github/workflows/render.yml")
    for name, job in d["jobs"].items():
        assert "add-mask" in job["steps"][0]["run"], name
        assert "voice_clip_urls" in job["steps"][0]["run"], name  # the owner's voice clips are presigned too


def test_render_never_uploads_artifacts_or_echoes_payload():
    txt = (ROOT / ".github/workflows/render.yml").read_text()
    assert "upload-artifact" not in txt and "toJson(github.event" not in txt and "toJSON(github.event" not in txt
    assert "cat $GITHUB_EVENT_PATH" not in txt and "set -x" not in txt


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


def test_dub_job_wires_parler_mirror_without_secrets():
    """WP12: weights come from the verified private-R2 mirror, cached by revision, loaded offline; no HF token."""
    d = load(ROOT / ".github/workflows/render.yml")
    steps = d["jobs"]["dub"]["steps"]
    names = [s.get("name", s.get("uses", "")) for s in steps]
    ci = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache") and "parler" in str(s["with"]["path"]))
    fi = next(i for i, s in enumerate(steps) if s.get("id") == "model")
    ti = next(i for i, s in enumerate(steps) if s.get("id") == "tts")
    assert ci < fi < ti, names
    assert "client_payload.model.revision" in steps[ci]["with"]["key"] and "parler" in steps[ci]["if"]
    assert "fetch-model" in steps[fi]["run"] and "parler" in steps[fi]["if"]
    tts = steps[ti]
    assert "steps.model.outputs.hub" in tts["env"]["PARLER_HUB"]
    assert "HF_HUB_CACHE" in tts["run"] and "HF_HUB_OFFLINE=1" in tts["run"]
    txt = (ROOT / ".github/workflows/render.yml").read_text()
    assert "HF_TOKEN" not in txt and "HUGGING_FACE_HUB_TOKEN" not in txt
    assert not any("secrets." in str(s) for s in steps)
    assert txt.count(".model.url") == 3  # every job masks the model URL first
    assert txt.count(".studio.music_urls") == 3  # and the studio music URLs
    for p in WF:
        assert "HF_TOKEN" not in p.read_text()


def test_master_uploads_even_when_qa_fails_and_dubs_wait_for_master():
    j = load(ROOT / ".github/workflows/render.yml")["jobs"]
    steps = j["master"]["steps"]
    names = [s.get("name", "") for s in steps]
    qa_i = next(i for i, n in enumerate(names) if n.startswith("QA gates"))
    up_i = next(i for i, n in enumerate(names) if n == "Upload outputs")
    assert up_i > qa_i and steps[up_i]["if"].startswith("always()")  # failed render stays reviewable (qa.json + master.mp4)
    assert steps[qa_i]["if"] == "always()" and "studio-export" in steps[qa_i]["run"]  # a failed voice/studio step still writes qa
    assert "dub" not in steps[up_i]["run"] and "master" in j["dub"]["needs"]  # default if: success() keeps dubs off


def test_voice_gate_lines_are_public_safe_and_the_render_waits_for_the_voice_step():
    steps = _steps("master")
    names = [s.get("name", "") for s in steps]
    voice = next(s for s in steps if s.get("name", "").startswith("Voice"))
    assert "\\[voice-gate\\]" in voice["run"] and "exit $rc" in voice["run"]
    render = next(s for s in steps if s.get("name", "").startswith("Studio render"))
    assert "if" not in render, "the render must be skipped when the voice step (phase 2) fails"
    assert names.index(voice["name"]) < names.index(render["name"])
    qa = next(s for s in steps if s.get("name", "").startswith("QA gates"))
    assert qa["if"] == "always()"


def test_dub_job_skips_only_after_a_failed_master_and_has_step_timeouts_and_shared_cache():
    j = load(ROOT / ".github/workflows/render.yml")["jobs"]
    cond = j["dub"]["if"]
    assert "needs.master.result == 'success'" in cond and "needs.master.result == 'skipped'" in cond and "failure" not in cond
    assert "always()" in cond  # evaluated even though the master job is skipped on the dub proof run
    assert j["master"]["if"] == "github.event.inputs.fixture != 'studio-short-dub'"
    steps = {s.get("name", ""): s for s in j["dub"]["steps"]}
    assert steps["TTS (voice clone or stock voice per languages.yaml)"]["timeout-minutes"] < j["dub"]["timeout-minutes"]
    cache = next(s for s in j["dub"]["steps"] if str(s.get("uses", "")).startswith("actions/cache") and "huggingface" in str(s["with"]["path"]))
    assert "matrix.lang" not in cache["with"]["key"] and "matrix.cache" in cache["with"]["key"]


def test_every_dub_always_reports_a_result_and_the_fixture_dub_uploads_nothing():
    steps = _steps("dub")
    up = next(s for s in steps if s.get("id") == "upload")
    assert up["if"].startswith("always()") and "repository_dispatch" in up["if"]
    rep = next(s for s in steps if s.get("name", "").startswith("Report a failed dub"))
    assert rep["if"].startswith("always()") and ".qa_uploaded" in rep["run"] and "qa_${LANG_CODE}.json" in rep["run"]
    assert "set +x" in rep["run"] and "-v" not in rep["run"].replace("--max-time", "")
    for s in steps:
        r = s.get("run", "")
        if "fetch --payload" in r or "upload --payload" in r:
            assert "repository_dispatch" in s["if"], s.get("name")


def test_dub_fixture_inputs_and_plan():
    on = load(ROOT / ".github/workflows/render.yml")["on"]
    assert on["workflow_dispatch"]["inputs"]["fixture"]["options"] == ["studio-short", "studio-short-dub"]
    from ullaslab_engine.studio.fixture import payload_free_plan
    assert payload_free_plan() == ['matrix={"include": []}', "has_dubs=false"]
    assert '"lang": "es"' in payload_free_plan("es")[0] and payload_free_plan("es")[1] == "has_dubs=true"


def test_cache_key_part_has_no_comma_for_any_language(capsys):
    """actions/cache rejects commas in a key (the one dub fixture run failed on `chatterbox,kokoro`): plan emits a comma-free part."""
    import json as _j
    from ullaslab_engine import cli
    from ullaslab_engine.config import languages
    for code, cfg in languages().items():
        if cfg.get("dub"):
            k = cli._cache_key(code)
            assert k and "," not in k and " " not in k, code
    from ullaslab_engine.studio.fixture import payload_free_plan
    assert "," not in _j.loads(payload_free_plan("es")[0].removeprefix("matrix="))["include"][0]["cache"]
