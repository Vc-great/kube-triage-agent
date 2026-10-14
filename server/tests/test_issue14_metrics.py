"""Offline metrics contracts; every fixture here is synthetic."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_metrics as metrics


def ai(ident="model-1", usage=None, response=None, calls=None):
    item = {"type": "ai", "name": "triage_llm", "id": ident,
            "tool_calls": calls or []}
    if usage is not None:
        item["usage_metadata"] = usage
    if response is not None:
        item["response_metadata"] = {"token_usage": response}
    return item


@pytest.mark.parametrize(("usage", "response", "expected", "status"), [
    ({"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}, None, 5, "observed"),
    (None, {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}, 5, "observed"),
    ({"input_tokens": 3, "output_tokens": 2}, {"total_tokens": 99}, 5, "derived"),
    ({"total_tokens": 5}, None, 5, "observed"),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, None, 0, "observed"),
    ({"input_tokens": -1, "output_tokens": True, "total_tokens": "5"}, None, None, "unknown"),
    (None, None, None, "unknown"),
])
def test_usage_sources_and_missing(usage, response, expected, status):
    result = metrics.usage_message(ai(usage=usage, response=response))
    assert result["total"]["value"] == expected
    assert result["total"]["status"] == status
    if usage == {"total_tokens": 5}:
        assert result["input"]["value"] is None
        assert result["output"]["value"] is None


def test_usage_details_inconsistency_and_message_identity():
    item = ai(usage={"input_tokens": 10, "output_tokens": 3, "total_tokens": 12,
                     "input_token_details": {"cache_read": 4},
                     "output_token_details": {"reasoning": 2}})
    usage = metrics.usage_message(item)
    assert usage["inconsistent"]
    assert usage["details"]["input_token_details.cache_read"]["value"] == 4
    assert usage["details"]["output_token_details.reasoning"]["value"] == 2
    assert metrics.model_messages([item, item])["observed_decisions"]["value"] == 1
    conflict = [item, item | {"usage_metadata": {"total_tokens": 20}}]
    assert "model_message_id_conflict" in metrics.model_messages(conflict)["missing_reasons"]
    assert metrics.model_messages([ai(ident="")])["totals"]["total"]["value"] is None
    assert metrics.model_messages([item, {"type": "ai", "content": "fallback"}])[
        "observed_decisions"]["value"] == 1


def tool(call_id, *, status="success", ok=True, result='{"a": 1}', error_type=None):
    return {"type": "tool", "tool_call_id": call_id, "status": status,
            "content": json.dumps({"ok": ok, "result": result, "error_type": error_type})}


@pytest.mark.parametrize(("message", "key"), [
    (tool("one"), "wrapper_success"),
    (tool("one", status="success", ok=False), "wrapper_error"),
    (tool("one", status="error", ok=False, error_type="policy"), "policy_rejected"),
    (tool("one", status="error", ok=False, error_type="budget"), "budget_skipped"),
    (tool("one", status="error", ok=True), "unknown"),
])
def test_tool_envelopes(message, key):
    result = metrics.tool_metrics([ai(calls=[{"id": "one"}]), message])
    assert result[key]["value"] == 1
    assert result["mcp_transport_attempts"]["value"] is None


def test_tool_pairing_and_content_are_separate():
    messages = [ai(calls=[{"id": "one"}, {"id": "one"}]), tool("one")]
    result = metrics.tool_metrics(messages)
    assert result["matched_tool_responses"]["value"] == 0
    assert result["unknown_or_unpaired"]["value"] == 3
    for body, expected in (("{bad-json", "content_invalid"),
                           ("not: [valid yaml", "content_invalid"),
                           ("meaningless text", "content_unverified")):
        result = metrics.tool_metrics([ai(calls=[{"id": "one"}]), tool("one", result=body)])
        assert result["wrapper_success"]["value"] == 1
        assert result[expected]["value"] == 1
    assert metrics.tool_metrics([ai(calls=[{"id": ""}]), tool("wrong")])[
        "unknown_or_unpaired"]["value"] == 2


@pytest.mark.parametrize(("n", "p50", "p95"), [
    (0, None, None), (1, 1, 1), (2, 1.5, 2), (12, 6.5, 12),
    (24, 12.5, 23), (48, 24.5, 46),
])
def test_latency_nearest_rank(n, p50, p95):
    result = metrics.latency(list(range(1, n + 1)))
    assert result["p50"]["value"] == p50
    assert result["p95"]["value"] == p95
    assert (result["warning"] == "LOW_SAMPLE_WARNING") is (n < 20)


def test_latency_missing_and_success_failure_groups():
    assert metrics.latency([1, None, 3])["missing_count"] == 1
    rows = [metrics.normalize({"case_id": "a", "repeat": i, "run_status": status,
                               "elapsed_seconds": elapsed}, {}, "phase3a-baseline")
            for i, status, elapsed in ((1, "success", 1), (2, "fail", 3))]
    group = metrics.summarize(rows)["phase3a_mock"]
    assert group["latency"]["success"]["p50"]["value"] == 1
    assert group["latency"]["failure"]["p50"]["value"] == 3
    assert rows[0]["model_latency"]["value"] is None
    assert rows[0]["mcp_latency"]["value"] is None


def price():
    return {"provider": "fictional-provider", "billing_entity": "fictional-billing",
            "model_deployment": "fictional-model", "currency": "USD", "unit": "per_1m_tokens",
            "input_uncached_rate": "2", "input_cached_rate": "1", "output_rate": "4",
            "effective_at": "2026-01-01T00:00:00Z", "source_checked_at": "2026-01-01T00:00:00Z",
            "source_url_or_document": "fictional contract", "assumptions": "synthetic test only"}


def test_cost_strict_price_and_cache():
    tokens = {"input": metrics.metric(1000, "tokens", 1, "synthetic"),
              "output": metrics.metric(500, "tokens", 1, "synthetic")}
    details = {"input_token_details.cache_read": metrics.metric(200, "tokens", 1, "synthetic")}
    row = {"provider": "fictional-provider", "model_name": "fictional-model", "currency": "USD",
           "provider_verified": True, "hidden_retries_unknown": False,
           "run_at": "2026-02-01T00:00:00Z"}
    assert metrics.estimated_cost(tokens, details, price(), row)["value"] == "0.0038"
    assert metrics.estimated_cost(tokens, {}, price(), row)["value"] is None
    assert metrics.estimated_cost(tokens, details, None, row)["value"] is None
    assert metrics.estimated_cost(tokens, details, price(), row | {"currency": "EUR"})[
        "value"] is None
    assert metrics.estimated_cost(tokens, details, price(), row | {"hidden_retries_unknown": True})[
        "value"] is None
    assert metrics.estimated_cost(tokens, details, price(), row | {
        "run_at": "2025-01-01T00:00:00Z"})["value"] is None
    assert metrics.estimated_cost(tokens | {"input": metrics.metric(None, "tokens", 1, "synthetic")},
                                  details, price(), row)["value"] is None


def test_issue12_adapter_and_dry_run(tmp_path, monkeypatch, capsys):
    source = tmp_path / ".local/eval-runs/example"
    source.mkdir(parents=True, mode=0o700)
    (source / "runs.json").write_text(json.dumps([{"case_id": "a", "repeat": 1,
                                                    "arm": "A", "elapsed_seconds": 1.2}]))
    (source / "runs.json").chmod(0o600)
    monkeypatch.setattr(metrics, "PROJECT_HOME", tmp_path)
    monkeypatch.setattr(metrics, "METRICS_ROOT", tmp_path / ".local/eval-metrics")
    out = metrics.METRICS_ROOT / "issue14-test"
    assert metrics.main(["--source", str(source), "--dataset", "issue12-blind-v1",
                         "--out", str(out), "--dry-run"]) == 0
    assert not metrics.METRICS_ROOT.exists()
    assert "NO NETWORK" in capsys.readouterr().out
    assert metrics.main(["--source", str(source), "--dataset", "issue12-blind-v1",
                         "--out", str(out)]) == 0
    result = json.loads((out / "metrics.json").read_text())
    assert result["runs"][0]["source_measurement_present"] is False
    assert result["runs"][0]["llm"]["totals"]["total"]["value"] is None
    assert (out.stat().st_mode & 0o777) == 0o700
    assert ((out / "metrics.json").stat().st_mode & 0o777) == 0o600
    with pytest.raises(ValueError):
        metrics.checked_paths(source, out)
    with pytest.raises(ValueError):
        metrics.checked_paths(source, source)
    symlink = tmp_path / ".local/eval-metrics/issue14-link"
    symlink.symlink_to(out)
    with pytest.raises(ValueError):
        metrics.checked_paths(source, symlink)
