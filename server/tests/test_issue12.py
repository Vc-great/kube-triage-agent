"""Issue #12 offline contract and negative trajectory cases."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kube_triage import llm, prompts

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_issue12 as runner


def test_blind_cases_and_fixtures():
    cases = runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
    assert len(cases) == 8
    assert {case["id"] for case in cases} == set("abcdefgh")
    for case in cases:
        assert case["target_pod"] in case["question"]
        assert case["ground_truth"] not in case["question"]
    fixtures = [json.loads(path.read_text()) for path in (
        ROOT / "server/src/kube_triage/fixtures/issue12").glob("*.json")]
    assert len(fixtures) == 9
    assert any(item["name"] == "sample-noise" and item["events"][0]["type"] == "Warning"
               for item in fixtures)
    assert any(not event.get("uid") for item in fixtures for event in item["events"])
    assert all(event.get("uid") in {None, item["uid"]} for item in fixtures
               for event in item["events"])


@pytest.mark.parametrize(("mode", "variant", "suffix"), [
    ("test", "A", False), ("test", "B", True),
    ("production", "B", False), ("development", "B", False)])
def test_prompt_isolation(monkeypatch, mode, variant, suffix):
    monkeypatch.setenv("TRIAGE_ENV", mode)
    monkeypatch.setenv("EVAL_PROMPT_VARIANT", variant)
    value = prompts.system_prompt()
    assert value.startswith(prompts.SYSTEM_PROMPT)
    assert (value != prompts.SYSTEM_PROMPT) is suffix
    if suffix:
        assert value == prompts.SYSTEM_PROMPT + prompts.ISSUE12_CAUSAL_SUFFIX


def test_unknown_variant_fails_closed(monkeypatch):
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("EVAL_PROMPT_VARIANT", "C")
    with pytest.raises(ValueError):
        prompts.system_prompt()


def test_luna_config_and_key_not_leaked(monkeypatch):
    captured = []
    monkeypatch.setattr(llm, "ChatOpenAI", lambda **kwargs: captured.append(kwargs))
    for arm in ("A", "B"):
        monkeypatch.setenv("TRIAGE_ENV", "test")
        monkeypatch.setenv("EVAL_PROMPT_VARIANT", arm)
        monkeypatch.setenv("EVAL_LUNA_RESPONSES_HIGH", "true")
        monkeypatch.setenv("LLM_MODEL", "gpt-6-luna")
        monkeypatch.setenv("LLM_API_KEY", "private-sentinel")
        llm.chat_model()
    assert captured[0] == captured[1]
    assert captured[0]["use_responses_api"] is True
    assert captured[0]["reasoning"] == {"effort": "high"}
    assert captured[0]["max_retries"] == 1
    assert "private-sentinel" not in str({k: v for k, v in captured[0].items() if k != "api_key"})
    monkeypatch.setenv("TRIAGE_ENV", "production")
    llm.chat_model()
    assert "reasoning" not in captured[-1]
    monkeypatch.setenv("TRIAGE_ENV", "development")
    llm.chat_model()
    assert captured[-1]["reasoning"] == {"effort": "high"}


def test_mock_dataset_selection(monkeypatch):
    from kube_triage import mock_mcp
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "issue12-blind-v1")
    assert len(mock_mcp.load_pods()) == 9
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "typo")
    with pytest.raises(ValueError):
        mock_mcp.load_pods()
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "issue12-blind-v1")
    monkeypatch.setenv("TRIAGE_ENV", "production")
    with pytest.raises(ValueError):
        mock_mcp.load_pods()


def _messages(result, *, uid=True, status="success", ok=True, call_id="one"):
    event = {"type": "Warning", "reason": "Failed", "involvedObject": {
        "kind": "Pod", "name": "sample-c", "namespace": "kube-triage-demo"}}
    if uid:
        event["involvedObject"]["uid"] = "synthetic-c"
    return [{"type": "ai", "name": "triage_llm", "tool_calls": [{
        "id": call_id, "name": "events_list", "args": {"namespace": "kube-triage-demo"}}]},
        {"type": "tool", "tool_call_id": call_id, "status": status,
         "content": json.dumps({"ok": ok, "result": {"mock": True,
             "source": "static-fixture", "events": [event]}})},
        {"type": "ai", "name": "triage_llm", "content": "待审阅"}]


def test_trajectory_pairing_success_and_weak_uid():
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    good = runner.inspect(_messages(None), case)
    assert good["tool_message_match"] and good["tool_success_count"] == 1
    assert "target_event_weak" in good["evidence_keys"]
    assert not good["evidence_sufficient"]
    weak = runner.inspect(_messages(None, uid=False), case)
    assert "target_event_weak" in weak["evidence_keys"]
    assert not weak["evidence_sufficient"]
    bad = _messages(None, status="error")
    assert runner.inspect(bad, case)["tool_success_count"] == 0
    bad = _messages(None, ok=False)
    assert runner.inspect(bad, case)["tool_success_count"] == 0
    bad = _messages(None)
    bad[1]["tool_call_id"] = "wrong"
    assert not runner.inspect(bad, case)["tool_message_match"]
    bad = _messages(None)
    bad.insert(1, bad[0]["tool_calls"][0])
    bad.pop(1)
    bad[0]["tool_calls"].append(bad[0]["tool_calls"][0])
    assert not runner.inspect(bad, case)["tool_message_match"]


def test_trajectory_selector_budget_noise_and_order():
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    messages = _messages(None)
    messages[0]["tool_calls"][0]["args"]["namespace"] = "kube-system"
    assert not runner.inspect(messages, case)["tool_selection_compliant"]
    messages = _messages(None)
    messages[-1]["content"] = "已达到本轮模型决策上限（4 轮）"
    assert runner.inspect(messages, case)["budget_exhausted"]
    messages = _messages(None)
    messages[0]["tool_calls"].append({"id": "two", "name": "pods_get", "args": {
        "namespace": "kube-triage-demo", "name": "sample-noise"}})
    messages.insert(2, {"type": "tool", "tool_call_id": "two", "status": "success",
                        "content": json.dumps({"ok": True, "result": {"mock": True,
                            "source": "static-fixture", "name": "sample-noise"}})})
    assert runner.inspect(messages, case)["unrelated_tool_calls"] == 1
    assert runner.inspect(messages, case)["tool_message_match"]


def test_timeout_empty_evidence_and_order_independence():
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    empty = [{"type": "ai", "name": "triage_llm", "content": "证据不足"}]
    assert not runner.inspect(empty, case)["evidence_sufficient"]
    timeout = _messages(None, status="error", ok=False)
    assert runner.inspect(timeout, case)["tool_failure_count"] == 1
    get_call = {"id": "two", "name": "pods_get", "args": {
        "namespace": "kube-triage-demo", "name": "sample-c"}}
    detail = {"mock": True, "source": "static-fixture", "name": "sample-c",
              "metadata": {"uid": "synthetic-c"}, "status": {
        "phase": "Pending", "containerStatuses": [{"state": {
            "waiting": {"reason": "ImagePullBackOff"}}}]}}
    get_msg = {"type": "tool", "tool_call_id": "two", "status": "success",
               "content": json.dumps({"ok": True, "result": detail})}
    for before in (True, False):
        messages = _messages(None)
        messages[0]["tool_calls"].append(get_call)
        if before:
            messages.insert(1, get_msg)
        else:
            messages.insert(3, get_msg)
        result = runner.inspect(messages, case)
        assert result["tool_message_match"] and result["evidence_sufficient"]
        assert result["tool_success_count"] == 2


def test_output_path_and_dry_run_no_credentials(tmp_path):
    with pytest.raises(ValueError):
        runner.output_path(Path(".local/eval-runs/phase3a-baseline"))
    with pytest.raises(ValueError):
        runner.output_path(tmp_path / "issue12-outside")
    base = runner.ROOT / ".local/eval-runs"
    base.mkdir(parents=True, exist_ok=True)
    existing = base / "issue12-existing-test"
    existing.mkdir(exist_ok=True)
    with pytest.raises(ValueError):
        runner.output_path(existing)
    link = base / "issue12-link-test"
    try:
        link.symlink_to(existing)
        with pytest.raises(ValueError):
            runner.output_path(link)
    finally:
        link.unlink(missing_ok=True)
        existing.rmdir()
    env = {key: value for key, value in os.environ.items() if key not in {
        "LLM_API_KEY", "DEMO_API_TOKEN"}}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/eval_issue12.py"),
                             "--out", ".local/eval-runs/issue12-dry-test", "--dry-run"],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert '"total_runs": 48' in result.stdout
    assert not (base / "issue12-dry-test").exists()
    smoke = subprocess.run([sys.executable, str(ROOT / "scripts/eval_issue12.py"),
                            "--out", ".local/eval-runs/issue12-smoke-dry-test",
                            "--smoke-case", "a", "--arms", "A", "--repeats", "1",
                            "--max-runs", "1", "--dry-run"],
                           cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert '"total_runs": 1' in smoke.stdout
    assert not (base / "issue12-smoke-dry-test").exists()


def test_rubric_remains_pending():
    case = runner.load_cases(ROOT / "eval/issue12/blind-v1.json")[0]
    review = runner.rubric("A", case, 1)
    assert review["diagnosis_correct"] == "PENDING"
    assert review["tool_message_ids"] == []
    assert runner.summary([], ["A", "B"], 24)["quality"].startswith("PENDING")
