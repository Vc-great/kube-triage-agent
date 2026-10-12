"""Offline checks for the shared Mock facts and real-run result parser."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

from kube_triage import mock_mcp
from kube_triage.mcp_client import NAMESPACE

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("eval_phase3a", ROOT / "scripts" / "eval_phase3a.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_four_native_tools_and_consistent_pods():
    assert {tool.name for tool in mock_mcp.mcp._tool_manager.list_tools()} == {
        "pods_list_in_namespace", "pods_get", "events_list", "pods_log"}
    listing = mock_mcp.pods_list_in_namespace(NAMESPACE)
    assert {p["name"] for p in listing["pods"]} == set(mock_mcp.PODS)
    for pod in listing["pods"]:
        detail = mock_mcp.pods_get(NAMESPACE, pod["name"])
        assert detail["mock"] and detail["source"] == "static-fixture"
        assert detail["status"]["phase"] == pod["phase"]
        assert detail["status"]["containerStatuses"]
    assert mock_mcp.pods_get(NAMESPACE, "crashloop-pod")["status"]["phase"] == "Running"
    assert mock_mcp.pods_get(NAMESPACE, "oom-pod")["status"]["containerStatuses"][0][
        "lastState"]["terminated"]["reason"] == "OOMKilled"


def test_events_keep_pod_association_and_imagepull_has_no_log():
    events = mock_mcp.events_list(NAMESPACE)["events"]
    assert len(events) == 4
    assert {e["involvedObject"]["name"] for e in events} == set(mock_mcp.PODS)
    assert next(e for e in events if e["involvedObject"]["name"] == "healthy-pod")[
        "type"] == "Normal"
    log = mock_mcp.pods_log(NAMESPACE, "imagepull-pod", tail=10, container="app")
    assert log["mock"] and log["source"] == "static-fixture"
    assert log["available"] is False and log["logs"] is None
    assert "database unavailable" in mock_mcp.pods_log(
        NAMESPACE, "crashloop-pod", container="app")["logs"]
    assert mock_mcp.pods_log(NAMESPACE, "crashloop-pod", tail=1)["logs"] == "exiting with code 1"
    with pytest.raises(ValueError):
        mock_mcp.pods_log(NAMESPACE, "healthy-pod", container="wrong")
    with pytest.raises(ValueError):
        mock_mcp.events_list("kube-system")


def test_golden_is_neutral_and_complete():
    cases = runner.load_cases(ROOT / "eval" / "cases.json")
    assert len(cases) == 4
    for case in cases:
        assert case["expected_label"] not in case["question"]
        assert case["target_pod"] in mock_mcp.PODS


def tool_message(call_id, result):
    return {"type": "tool", "tool_call_id": call_id, "status": "success",
            "content": json.dumps({"ok": True, "result": json.dumps(result)})}


def test_parser_requires_current_target_evidence_and_pairing():
    healthy = next(c for c in runner.load_cases(ROOT / "eval" / "cases.json")
                   if c["id"] == "healthy")
    call = {"name": "events_list", "args": {"namespace": NAMESPACE}, "id": "one"}
    messages = [{"type": "ai", "name": "triage_llm", "tool_calls": [call]},
                tool_message("one", mock_mcp.events_list(NAMESPACE)),
                {"type": "ai", "name": "triage_llm", "content": "暂无故障证据"}]
    result = runner.inspect_messages(messages, healthy)
    assert result["tool_message_match"]
    assert "target_event" not in result["evidence_keys"]
    assert not result["evidence_sufficient"]
    messages.insert(2, {"type": "ai", "name": "triage_llm", "tool_calls": [{
        "name": "pods_get", "args": {"namespace": NAMESPACE, "name": "healthy-pod"}, "id": "two"}]})
    messages.insert(3, tool_message("two", mock_mcp.pods_get(NAMESPACE, "healthy-pod")))
    assert runner.inspect_messages(messages, healthy)["evidence_sufficient"]
    messages[3]["tool_call_id"] = "wrong"
    assert not runner.inspect_messages(messages, healthy)["tool_message_match"]


def test_review_metrics_never_autopass():
    rows = [{"case_id": "healthy", "repeat": 1}]
    assert runner.score_reviews(rows, [{"case_id": "healthy", "repeat": 1,
        "diagnosis_correct": None}], 1)["status"] == "PENDING"
    review = {"case_id": "healthy", "repeat": 1, "diagnosis_correct": 0,
              "grounding_score": 1, "false_positive": 1}
    result = runner.score_reviews(rows, [review], 1)
    assert result["diagnosis_accuracy"] == 0
    assert result["healthy_false_positive_rate"] == 1


def test_sse_parser_and_budget_result(monkeypatch):
    class Stream(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *_args, **_kwargs: Stream(
        b"event: values\ndata: {}\n\nevent: end\ndata: {}\n\n"))
    events = runner.stream_run("http://127.0.0.1:12028", "unused", "thread", "question", 10)
    assert [event["event"] for event in events] == ["values", "end"]
    case = next(c for c in runner.load_cases(ROOT / "eval" / "cases.json")
                if c["id"] == "crashloop")
    result = runner.inspect_messages([{"type": "ai", "content": "已达到本轮模型决策上限（4 轮）"}],
                                     case)
    assert result["budget_or_error_answer"] and not result["tool_message_match"]
    assert not runner.valid_call("events_list", {"namespace": "kube-system"})
