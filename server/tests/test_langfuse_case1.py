"""Synthetic tests only: fail if report mode attempts models or runtime processes."""

import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import dev
import langfuse_case1 as case
import obs_lab as lab
from obs_lab_score_upload import ScoreCloud
from obs_lab_verify import content_digest, verify_cloud
from test_obs_lab import complete_evidence


@pytest.mark.parametrize("url", ["http://localhost:3000/", "https://127.0.0.1:443",
                                "http://[::1]:3000", "https://jp.cloud.langfuse.com/"])
def test_allowed_origins(url):
    assert dev.normalize_langfuse_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", ["http://localhost:0", "http://localhost:65536", "http://localhost:",
                                "http://user:secret@localhost:3000", "http://localhost:3000/?secret=abc",
                                "http://localhost:3000/#secret", "http://localhost:3000/api",
                                "http://localhost.evil:3000", "https://example.test",
                                "http://localhost:3000?", "http://localhost:3000#",
                                "http://localhost\\@evil", " http://localhost:3000"])
def test_invalid_origins_do_not_echo_value(url):
    with pytest.raises(RuntimeError, match="LANGFUSE_URL_INVALID") as error:
        dev.normalize_langfuse_url(url)
    assert url not in str(error.value)


def test_case1_and_score_upload_reject_wrong_destination():
    with pytest.raises(RuntimeError):
        dev.normalize_langfuse_url("https://jp.cloud.langfuse.com", local_only=True)
    with pytest.raises(ValueError):
        ScoreCloud({"LANGFUSE_BASE_URL": "http://localhost:3000"})


def test_api_and_links_share_validated_origin(monkeypatch):
    seen = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self):
            return b'{"data":[]}'

    class Opener:
        def open(self, request, timeout):
            seen.append(request.full_url)
            return Response()

    def opener(*handlers):
        redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        assert len(redirects) == 1
        assert redirects[0].redirect_request(None, None, 302, "", {}, "https://evil.test") is None
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    client = lab.Cloud({"LANGFUSE_PUBLIC_KEY": "fake", "LANGFUSE_SECRET_KEY": "fake",
                        "LANGFUSE_BASE_URL": "http://localhost:3000"})
    assert client.get("projects") == {"data": []}
    assert seen == ["http://localhost:3000/api/public/projects"]
    with pytest.raises(RuntimeError):
        client.get("../outside")
    row, observations = complete_evidence()
    assert verify_cloud(observations, row, "agent-lab", base_url=client.base_url)["url"].startswith(
        "http://localhost:3000/project/agent-lab/traces/")
    assert verify_cloud(observations, row, "p")["url"].startswith("https://jp.cloud.langfuse.com/")


def test_wrong_project_blocks_before_model_or_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "read_langfuse_env", lambda p: {"LANGFUSE_BASE_URL": "http://localhost:3000"})
    monkeypatch.setattr(lab.Cloud, "get", lambda *a: {"data": [{"id": "other", "name": "Agent Lab"}]})
    monkeypatch.setattr(lab, "configuration", lambda *a: pytest.fail("must not reach model configuration"))
    with pytest.raises(RuntimeError, match="PROJECT_MISMATCH"):
        case.preflight(tmp_path / ".env")


def test_init_credentials_stay_out_of_runtime(tmp_path, monkeypatch):
    source = tmp_path / ".env"
    source.write_text("LLM_MODEL=fake\nLLM_API_KEY=fake\nLANGFUSE_INIT_USER_EMAIL=private\n"
                      "LANGFUSE_INIT_USER_PASSWORD=private\n")
    source.chmod(0o600)
    monkeypatch.setattr(dev, "ENV_FILE", source)
    assert dev.read_env() == {"LLM_MODEL": "fake", "LLM_API_KEY": "fake"}


def test_budget_persists_and_does_not_replay_reserved_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(case, "DIRECTORY", tmp_path / "case1")
    with case.lock():
        path, state = case.activity(create=True)
        for scenario in case.SCENARIOS:
            for _ in range(2):
                case.reserve(path, state, scenario)
        with pytest.raises(RuntimeError, match="BUDGET"):
            case.reserve(path, state, "S01")
    _, recovered = case.activity(state["activity_id"])
    assert len(recovered["runs"]) == 6
    assert case.load_row(path, recovered["runs"][0])["execution_error"] == "incomplete_reserved_run"
    assert os.stat(path / "activity.json").st_mode & 0o777 == 0o600
    with case.lock(), pytest.raises(RuntimeError, match="BUSY"), case.lock():
        pytest.fail("double lock")


def test_evidence_mutation_is_detected(tmp_path):
    entry = {"key": "S01-1", "scenario_id": "S01", "repeat": 1}
    raw = tmp_path / "raw" / entry["key"]
    case.private_dir(raw)
    case.save(raw / "result.json", entry, exclusive=True)
    case.save(raw / "hashes.json", case.evidence_hashes(raw), exclusive=True)
    assert case.load_row(tmp_path, entry)["key"] == "S01-1"
    (raw / "result.json").write_text(json.dumps({**entry, "final_answer": "changed"}))
    with pytest.raises(RuntimeError, match="EVIDENCE_CHANGED"):
        case.load_row(tmp_path, entry)


def test_review_binds_source_reason_and_answer(tmp_path):
    case.private_dir(tmp_path / "reviews")
    row = {"run_id": "r", "final_answer": "证据不足"}
    review = {"source": "agent_review", "status": "FAIL", "reason": "合成反例",
              "answer_sha256": content_digest(row["final_answer"]), "rubric_version": "case1-v1"}
    case.save(tmp_path / "reviews/one.json", {"r": review}, exclusive=True)
    assert case.read_review(tmp_path, row)["status"] == "FAIL"
    with pytest.raises(RuntimeError, match="REVIEW_INVALID"):
        case.read_review(tmp_path, {**row, "final_answer": "other"})


def test_report_is_read_only_and_html_escaped(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "execute", lambda *a: pytest.fail("model Run forbidden"))
    monkeypatch.setattr(lab, "isolated", lambda *a: pytest.fail("runtime forbidden"))
    monkeypatch.setattr(case, "preflight", lambda *a: pytest.fail("report cannot run preflight"))
    row, observations = complete_evidence()
    row.update(key="S01-1", scenario_id="S01", repeat=1, protocol_status="success",
               start=observations[0]["startTime"], end=observations[0]["endTime"],
               final_answer="<script>alert(1)</script>", diagnosis_review={})
    monkeypatch.setattr(case, "load_row", lambda *a: deepcopy(row))

    class Client:
        base_url = "http://localhost:3000"
        def observations(self, *args, **kwargs):
            return observations

    state = {"activity_id": "case1", "langfuse_base_url": Client.base_url,
             "runs": [{"key": "S01-1"}]}
    report = case.build_report(tmp_path, state, Client())
    assert len(report["runs"]) == 6
    assert report["reserved_runs"] == 1
    page = next((tmp_path / "reports").glob("*/index.html")).read_text()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "UNKNOWN" in page
    first_files = {p: p.read_bytes() for p in (tmp_path / "reports").glob("*/*")}
    case.build_report(tmp_path, state, Client())
    assert all(p.read_bytes() == b for p, b in first_files.items())


def test_timeout_cleans_up_and_keeps_reserved_evidence(tmp_path, monkeypatch):
    calls = []
    @contextmanager
    def isolated(*args):
        try:
            yield "http://example.test", "fake"
        finally:
            calls.append("cleanup")
    monkeypatch.setattr(lab, "isolated", isolated)
    def execute(*args):
        raise TimeoutError("synthetic")
    monkeypatch.setattr(lab, "execute", execute)
    monkeypatch.setattr(case, "refresh", lambda cloud, row: row.update(case1_trace_ready=True) or [])
    client = type("Client", (), {})()
    row = case.execute_one(tmp_path, {"activity_id": "case1"}, {
        "key": "S01-1", "scenario_id": "S01", "repeat": 1}, {}, {}, client, 1)
    assert calls == ["cleanup"]
    assert row["execution_error"] == "TimeoutError"
    assert not case.infrastructure_valid(row)
    assert (tmp_path / "raw/S01-1/hashes.json").exists()


def test_exclusive_and_symlink_outputs(tmp_path):
    p = tmp_path / "x.json"
    case.save(p, {}, exclusive=True)
    with pytest.raises(FileExistsError):
        case.save(p, {}, exclusive=True)
    q = tmp_path / "link"
    q.symlink_to(p)
    with pytest.raises(RuntimeError):
        case.save(q, {})


def test_order_and_explicit_continue_never_replay(tmp_path, monkeypatch):
    row = {"scenario_id": "S01", "diagnosis_review": {"status": "FAIL"}, "case1_trace_ready": True}
    monkeypatch.setattr(case, "load_row", lambda *a: deepcopy(row))
    monkeypatch.setattr(case, "infrastructure_valid", lambda *a: True)
    monkeypatch.setattr(case, "refresh", lambda *a: [])
    state = {"runs": [{}]}
    with pytest.raises(RuntimeError, match="ALREADY_RUN"):
        case.assert_previous(tmp_path, state, "S01", None)
    assert case.assert_previous(tmp_path, state, "S01", None, resume=True) == 1
    with pytest.raises(RuntimeError, match="ORDER"):
        case.assert_previous(tmp_path, state, "S05", None)
    state["runs"].append({})
    assert case.assert_previous(tmp_path, state, "S05", None) == 0
    row["diagnosis_review"] = {}
    with pytest.raises(RuntimeError, match="REVIEW_REQUIRED"):
        case.assert_previous(tmp_path, state, "S05", None)


def test_nontrigger_does_not_become_fault_pass():
    row = {"scenario_id": "S05", "fault_evidence": {"fault_observed": False},
           "cloud": {"chain_verified": True, "scenario_observable": "BLOCKED"}}
    assert case.trace_ready(row)
    assert row["cloud"]["scenario_observable"] == "BLOCKED"


def test_compose_local_uses_host_and_excludes_accounts(tmp_path, monkeypatch):
    import compose_with_langfuse as compose

    source = tmp_path / ".env"
    source.write_text("LANGFUSE_PUBLIC_KEY=fake\nLANGFUSE_SECRET_KEY=fake\n"
                      "LANGFUSE_BASE_URL=http://localhost:3000\n")
    source.chmod(0o600)
    monkeypatch.setattr(compose, "ENV_FILE", source)
    _, env = compose.compose_invocation("test", "case1-test", ["config", "--quiet"], {
        "LANGFUSE_INIT_USER_PASSWORD": "never-pass", "LANGFUSE_SECRET_KEY": "host-key"})
    assert env["LANGFUSE_BASE_URL"] == "http://host.docker.internal:3000"
    assert "LANGFUSE_INIT_USER_PASSWORD" not in env
    assert env["LANGFUSE_SECRET_KEY"] == "fake"


def test_locked_otlp_transport_does_not_follow_redirects():
    # Verify the installed, locked exporter dependency, not a substitute client.
    from types import SimpleNamespace

    from opentelemetry.exporter.http.transport._requests import RequestsHTTPTransport

    calls = []

    class Session:
        def request(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status_code=307, reason="Temporary Redirect")

    transport = RequestsHTTPTransport(session=Session())
    result = transport.request("POST", "http://localhost:3000/api/public/otel/v1/traces",
                               headers={"Authorization": "synthetic"}, data=b"synthetic")
    assert result.status_code == 307
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False
