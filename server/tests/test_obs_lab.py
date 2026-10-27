"""Synthetic evidence tests: never contact a model, Cloud or Docker."""

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import obs_lab as lab


def test_isolation_never_inherits_host_secrets_or_kubeconfig(monkeypatch):
    monkeypatch.setenv("KUBECONFIG", "/private/real-cluster")
    monkeypatch.setenv("DATABASE_URL", "postgresql://stable")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "host-secret")
    values = {"LLM_MODEL": "synthetic", "LLM_API_KEY": "fake", "LLM_BASE_URL": "https://example.test"}
    api, mock = lab.environments(values, {}, {"pg": 1234, "redis": 1235, "api": 1236}, "batch", False)
    for environment in (api, mock):
        assert "KUBECONFIG" not in environment
        assert "DATABASE_URL" not in environment
        assert "LANGFUSE_SECRET_KEY" not in environment
    assert api["MCP_SERVER_URL"] == "http://127.0.0.1:8000/mcp"
    assert api["REPAIR_ENABLED"] == "false"
    assert api["BG_JOB_MAX_RETRIES"] == "0"
    assert mock["TRIAGE_ENV"] == "test"


@pytest.mark.parametrize("tracing", [True, False])
def test_local_proxy_is_fixed_and_only_in_api(monkeypatch, tracing):
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "unapproved.test")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.test:9999")
    values = {"LLM_MODEL": "synthetic", "LLM_API_KEY": "fake", "LLM_BASE_URL": "https://example.test"}
    api, mock = lab.environments(values, {}, {"pg": 1, "redis": 2, "api": 3}, "batch", tracing)
    assert api["HTTP_PROXY"] == api["HTTPS_PROXY"] == "http://127.0.0.1:33210"
    assert api["NO_PROXY"] == api["no_proxy"] == "localhost,127.0.0.1,::1,192.168.31.110"
    assert not any(key.lower().endswith("_proxy") for key in mock)


def test_requests_uses_33210_for_japan_but_not_local_services(monkeypatch):
    from urllib.request import getproxies_environment

    from requests import utils

    monkeypatch.setattr(utils, "getproxies", lambda: getproxies_environment() or {
        "https": "http://system-proxy.invalid:8888"})
    monkeypatch.setattr(utils, "proxy_bypass", lambda host: False)
    values = {"LLM_MODEL": "synthetic", "LLM_API_KEY": "fake", "LLM_BASE_URL": "https://example.test"}
    api, _ = lab.environments(values, {}, {"pg": 1, "redis": 2, "api": 3}, "batch")
    for key in ("http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, api[key])
    url = "https://jp.cloud.langfuse.com/api/public/otel/v1/traces"
    assert utils.select_proxy(url, utils.get_environ_proxies(url)) == "http://127.0.0.1:33210"
    for local in ("http://127.0.0.1:8000/mcp", lab.APPROVED_PROVIDER_URL):
        assert utils.select_proxy(local, utils.get_environ_proxies(local)) is None


def observation(identifier, kind, start, end, parent="root", trace="real"):
    start = f"2026-10-27T00:00:{int(start):02d}+00:00"
    end = f"2026-10-27T00:00:{int(end):02d}+00:00"
    return {"id": identifier, "type": kind, "traceId": trace,
            "sessionId": "thread", "metadata": {"run_id": "run"},
            "parentObservationId": parent, "startTime": start, "endTime": end}


def complete_evidence():
    call = {"id": "call-1", "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "sample-e"}}
    row = {"thread_id": "thread", "run_id": "run", "tool_pairs_valid": True,
           "history_tool_pairs_valid": True, "model_decisions": 2, "tool_calls": [call]}
    rows = [observation("root", "CHAIN", "0", "9", None),
            observation("a", "GENERATION", "1", "2"),
            observation("b", "TOOL", "3", "4"),
            observation("c", "GENERATION", "5", "6")]
    rows[1]["output"] = {"generations": [[{"message": {"kwargs": {"tool_calls": [call]}}}]]}
    rows[2].update(name="pods_get", input=call["args"])
    rows[3]["input"] = {"messages": [[{"kwargs": {"tool_call_id": "call-1", "content": "synthetic"}}]]}
    return row, rows


def test_cloud_requires_unique_mapping_and_a_proven_chain():
    row, rows = complete_evidence()
    result = lab.verify_cloud(rows, row, "project")
    assert result["trace_verified"] is True
    assert result["chain_verified"] is True
    assert result["chain_status"] == "PASS"
    assert result["tool_call_proof"][0]["tool_observation"] == "b"
    assert result["root_id"] == "root"
    rows.append(observation("other", "CHAIN", "0", "9", trace="ambiguous"))
    assert lab.verify_cloud(rows, row, "project")["trace_verified"] is False
    assert lab.verify_cloud([], row, "project")["status"] == "ingestion_pending"


@pytest.mark.parametrize("removed", ["root", "a", "b", "c"])
def test_missing_span_cannot_pass_even_when_trace_exists(removed):
    row, rows = complete_evidence()
    result = lab.verify_cloud([o for o in rows if o["id"] != removed], row, "p")
    assert result["trace_verified"] is True
    assert result["chain_verified"] is False
    assert result["chain_status"] == "BLOCKED"


@pytest.mark.parametrize("fault", ["time", "parent", "cycle", "run", "session", "tool_args", "tool_id", "history"])
def test_counts_do_not_prove_chain_when_evidence_is_wrong(fault):
    row, rows = complete_evidence()
    if fault == "time":
        rows[2]["endTime"] = "2026-10-27T00:00:07+00:00"
    elif fault == "parent":
        rows[2]["parentObservationId"] = "missing"
    elif fault == "cycle":
        rows[1]["parentObservationId"] = "c"
        rows[3]["parentObservationId"] = "a"
    elif fault == "run":
        rows[3]["metadata"] = {"run_id": "another-run"}
    elif fault == "session":
        rows[3]["sessionId"] = "another-thread"
    elif fault == "tool_args":
        rows[2]["input"] = {"namespace": "wrong", "name": "sample-e"}
    elif fault == "tool_id":
        rows[3]["input"] = {"messages": [{"kwargs": {"tool_call_id": "wrong"}}]}
    else:
        row["history_tool_pairs_valid"] = False
    assert lab.verify_cloud(rows, row, "p")["chain_verified"] is False


def test_cloud_pagination_preserves_time_and_session_bounds():
    cloud = lab.Cloud({})
    queries = []

    def get(path, query):
        queries.append(dict(query))
        return {"data": [{"id": len(queries)}],
                "meta": {"cursor": "next" if len(queries) == 1 else None}}

    cloud.get = get
    assert len(cloud.observations({"thread_id": "t"}, "start", "end")) == 2
    assert queries[1]["cursor"] == "next"
    assert all(q["sessionId"] == "t" and q["fromStartTime"] == "start"
               and q["toStartTime"] == "end" for q in queries)


def test_export_failure_summary_never_exposes_response_body(tmp_path):
    (tmp_path / "api.log").write_text("Failed to export spans batch code: 403 reason: private-body")
    result = lab.export_failures(tmp_path)
    assert result == {"failure_count": 1, "http_statuses": ["403"]}
    assert "private-body" not in str(result)


def test_total_run_deadline_interrupts_even_without_network_timeout():
    with pytest.raises(RuntimeError, match="总时间预算"), lab.run_deadline(0.01):
        time.sleep(1)


def test_duplicate_call_ids_are_not_valid_pairs():
    state = {"values": {"messages": [
        {"type": "ai", "tool_calls": [{"id": "same"}, {"id": "same"}]},
        {"type": "tool", "tool_call_id": "same"},
        {"type": "tool", "tool_call_id": "same"}]}}
    assert lab.inspect_run(state, [], [])["tool_pairs_valid"] is False


@pytest.mark.parametrize("url", ["https://unapproved.test/v1", "http://127.0.0.1:8317/v1",
                                "http://192.168.31.110:8317/v1?key=secret",
                                "http://192.168.31.110:8318/v1"])
def test_unapproved_provider_rejected_before_sending_credentials(url):
    with pytest.raises(RuntimeError, match="拒绝出站"):
        lab.validate_provider(url)


def test_partial_batch_cloud_recovery_uses_each_run_time_window(tmp_path):
    windows = []

    class ReadOnlyCloud:
        def observations(self, row, start, end):
            windows.append((row["run_id"], start, end))
            return []

    manifest = {"project_id": "p", "runs": [
        {"scenario_id": "S01", "repeat": 1, "thread_id": "t1", "run_id": "r1",
         "start": "2026-10-27T00:00:01+00:00", "end": "2026-10-27T00:00:02+00:00"},
        {"scenario_id": "S02", "repeat": 1, "thread_id": "t2", "run_id": "r2",
         "start": "2026-10-27T00:00:03+00:00", "end": "2026-10-27T00:00:04+00:00"},
        {"scenario_id": "S03", "repeat": 1, "start": "start-3", "end": "end-3"}]}
    assert lab.refresh_cloud(ReadOnlyCloud(), manifest, tmp_path) is False
    assert [w[0] for w in windows] == ["r1", "r2"]
    assert all("2026-10-" in start and start < end for _, start, end in windows)
    assert manifest["runs"][0]["cloud"]["status"] == "ingestion_pending"
    assert manifest["runs"][2]["cloud"]["status"] == "unknown"


def test_async_ingestion_waits_for_chain_not_just_trace(tmp_path):
    row, rows = complete_evidence()
    row.update(scenario_id="S01", repeat=1, start=rows[0]["startTime"], end=rows[0]["endTime"])
    manifest = {"project_id": "p", "runs": [row]}
    ticks = [0]

    class DelayedCloud:
        reads = 0

        def observations(self, *args, **kwargs):
            self.reads += 1
            return rows[:-1] if self.reads <= 2 else rows

    def sleep(seconds):
        ticks[0] += seconds

    cloud = DelayedCloud()
    assert lab.wait_for_chain(cloud, manifest, tmp_path, 30, now=lambda: ticks[0], sleep=sleep)
    assert cloud.reads == 4
    assert row["cloud"]["chain_verified"] is True


def test_incomplete_chain_exhausts_read_budget_without_replaying_run(tmp_path):
    row, rows = complete_evidence()
    row.update(scenario_id="S01", repeat=1, start=rows[0]["startTime"], end=rows[0]["endTime"])

    class PartialCloud:
        def observations(self, *args, **kwargs):
            return rows[:-1]

    ticks = [0]

    def sleep(seconds):
        ticks[0] += seconds

    manifest = {"project_id": "p", "runs": [row]}
    assert not lab.wait_for_chain(PartialCloud(), manifest, tmp_path, 30,
                                  now=lambda: ticks[0], sleep=sleep)
    assert row["cloud"]["trace_verified"]
    assert not row["cloud"]["chain_verified"]
    assert ticks[0] == 30


def test_history_must_match_real_tool_pairs_not_only_ids():
    from obs_lab_verify import history_matches

    call = {"id": "c", "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "sample-e"}}
    state = {"values": {"messages": [{"type": "ai", "tool_calls": [call]},
                                     {"type": "tool", "tool_call_id": "c", "content": "ok"}]}}
    assert history_matches(state, [deepcopy(state)])
    wrong = deepcopy(state)
    wrong["values"]["messages"][1]["content"] = "different evidence"
    assert not history_matches(state, [wrong])


@pytest.mark.parametrize("export_error", [False, True])
def test_flush_runs_after_native_workers_drain_without_changing_agent_result(export_error):
    from obs_lab_api import draining_lifespan

    events = []

    @asynccontextmanager
    async def native(app):
        events.append("start")
        yield
        events.append("workers-drained")

    class Provider:
        def force_flush(self, timeout_millis):
            assert timeout_millis == 10000
            events.append("native-flush")
            if export_error:
                raise OSError("synthetic failure")
            return True

    async def run():
        async with draining_lifespan(native, lambda: Provider())(None):
            events.append("agent-completed")

    asyncio.run(run())
    assert events == ["start", "agent-completed", "workers-drained", "native-flush"]


def test_retained_tool_history_matches_immediate_response_generation():
    row, rows = complete_evidence()
    second = {"id": "call-2", "name": "pods_log", "args": {"namespace": "kube-triage-demo", "name": "sample-e"}}
    row["tool_calls"].append(second)
    row["model_decisions"] = 3
    rows[3]["output"] = {"tool_calls": [second]}
    tool = observation("tool-2", "TOOL", "7", "7")
    tool.update(name="pods_log", input={**second["args"], "tail": 20})
    final = observation("d", "GENERATION", "8", "9")
    final["input"] = {"messages": [{"tool_call_id": "call-1"}, {"tool_call_id": "call-2"}]}
    rows.extend([tool, final])
    result = lab.verify_cloud(rows, row, "p")
    assert result["chain_verified"]
    assert [p["response_generation"] for p in result["tool_call_proof"]] == ["c", "d"]


def test_tool_id_mentioned_only_in_user_text_is_not_tool_message_proof():
    row, rows = complete_evidence()
    rows[3]["input"] = {"messages": [{"role": "user", "content": '{"tool_call_id":"call-1"}'}]}
    assert not lab.verify_cloud(rows, row, "p")["chain_verified"]


@pytest.mark.parametrize("name", ["events_list", "pods_list_in_namespace"])
def test_native_single_argument_tool_input_is_normalized_from_its_schema(name):
    row, rows = complete_evidence()
    call = {"id": "call-1", "name": name, "args": {"namespace": "kube-triage-demo"}}
    row["tool_calls"] = [call]
    rows[1]["output"] = {"tool_calls": [call]}
    rows[2].update(name=name, input="kube-triage-demo")
    assert lab.verify_cloud(rows, row, "p")["chain_verified"]
    rows[2]["input"] = "wrong-namespace"
    assert not lab.verify_cloud(rows, row, "p")["chain_verified"]


def test_scalar_input_is_not_guessed_for_multi_argument_tool():
    row, rows = complete_evidence()
    rows[2]["input"] = "kube-triage-demo"
    assert not lab.verify_cloud(rows, row, "p")["chain_verified"]


def test_history_with_missing_final_model_decision_is_not_complete_evidence():
    from obs_lab_verify import history_matches

    state = {"values": {"messages": [
        {"type": "ai", "response_metadata": {"model_name": "synthetic"},
         "tool_calls": [{"id": "c", "name": "events_list", "args": {"namespace": "kube-triage-demo"}}]},
        {"type": "tool", "tool_call_id": "c", "content": "synthetic"},
        {"type": "ai", "response_metadata": {"model_name": "synthetic"}, "content": "done"}]}}
    history = deepcopy(state)
    history["values"]["messages"].pop()
    assert not history_matches(state, [history])
    assert history_matches(state, [deepcopy(state)])
