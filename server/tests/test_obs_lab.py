"""Synthetic evidence tests: never contact a model, Cloud or Docker."""

import sys
import time
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


def observation(identifier, kind, start, end, parent="root", trace="real"):
    return {"id": identifier, "type": kind, "traceId": trace,
            "sessionId": "thread", "metadata": {"run_id": "run"},
            "parentObservationId": parent, "startTime": start, "endTime": end}


def test_cloud_requires_unique_runtime_mapping_and_causal_chain():
    row = {"thread_id": "thread", "run_id": "run", "tool_pairs_valid": True}
    observations = [observation("root", "CHAIN", "0", "9", None),
                    observation("a", "GENERATION", "1", "2"),
                    observation("b", "TOOL", "3", "4"),
                    observation("c", "GENERATION", "5", "6")]
    result = lab.verify_cloud(observations, row, "project")
    assert result["timeline_status"] == "PASS"
    assert result["chain_status"] == "UNKNOWN"  # Tool Call IDs still need Cloud proof.
    assert result["url"].endswith("/project/project/traces/real")
    observations.append(observation("other", "CHAIN", "0", "9", trace="ambiguous"))
    assert lab.verify_cloud(observations, row, "project") == {"status": "unknown"}
    assert lab.verify_cloud([], row, "project") == {"status": "ingestion_pending"}


def test_disconnected_or_wrong_order_spans_do_not_pass():
    row = {"thread_id": "thread", "run_id": "run", "tool_pairs_valid": True}
    observations = [observation("a", "GENERATION", "1", "2", None),
                    observation("b", "TOOL", "3", "4", None),
                    observation("c", "GENERATION", "5", "6", None)]
    assert lab.verify_cloud(observations, row, "project")["chain_status"] == "UNKNOWN"


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
