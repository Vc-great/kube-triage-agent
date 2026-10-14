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


def test_provider_transport_rejects_non_loopback_http():
    assert runner.provider_transport("http://127.0.0.1:9999") == "loopback_http"
    assert runner.provider_transport("https://example.com/v1") == "unverified_host_https"
    with pytest.raises(ValueError):
        runner.provider_transport("http://192.168.1.20/v1")
    with pytest.raises(ValueError):
        runner.provider_transport("http://example.com/v1")


def _uid_messages(event_uid="synthetic-c", pod_uid="synthetic-c", *,
                  pod_status="success", pod_ok=True, pod_message_id="two",
                  pod_first=False, event_name="sample-c", event_namespace="kube-triage-demo",
                  event_kind="Pod"):
    case_messages = _messages(None)
    event_reply = json.loads(case_messages[1]["content"])
    event = event_reply["result"]["events"][0]
    event["involvedObject"]["kind"] = event_kind
    event["involvedObject"].update({"name": event_name, "namespace": event_namespace})
    if event_uid is None:
        event["involvedObject"].pop("uid", None)
    else:
        event["involvedObject"]["uid"] = event_uid
    case_messages[1]["content"] = json.dumps(event_reply)
    call = {"id": "two", "name": "pods_get", "args": {
        "namespace": "kube-triage-demo", "name": "sample-c"}}
    pod = {"mock": True, "source": "static-fixture", "name": "sample-c",
           "metadata": {"uid": pod_uid}, "status": {"phase": "Pending",
           "containerStatuses": [{"state": {"waiting": {"reason": "ImagePullBackOff"}}}]}}
    reply = {"type": "tool", "tool_call_id": pod_message_id, "status": pod_status,
             "content": json.dumps({"ok": pod_ok, "result": pod})}
    case_messages[0]["tool_calls"].append(call)
    case_messages.insert(1 if pod_first else 2, reply)
    return case_messages


@pytest.mark.parametrize(("event_uid", "pod_uid", "expected_key", "mismatch", "unverified"), [
    ("synthetic-c", "synthetic-c", "target_event", 0, 0),
    ("synthetic-old", "synthetic-c", None, 1, 0),
    (None, "synthetic-c", "target_event_weak", 0, 0),
    ("", "synthetic-c", "target_event_weak", 0, 0),
    ("synthetic-c", "", "target_event_weak", 0, 1),
])
def test_event_uid_three_states(event_uid, pod_uid, expected_key, mismatch, unverified):
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    for pod_first in (True, False):
        result = runner.inspect(_uid_messages(event_uid, pod_uid, pod_first=pod_first), case)
        assert result["event_uid_mismatch"] == mismatch
        assert result["event_uid_unverified"] == unverified
        assert ("target_event" in result["evidence_keys"]) == (expected_key == "target_event")
        assert ("target_event_weak" in result["evidence_keys"]) == (
            expected_key == "target_event_weak")
        assert result["evidence_sufficient"] is (expected_key == "target_event")


def test_event_uid_unverified_and_wrong_resource():
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    for messages in (_messages(None), _uid_messages(pod_status="error"),
                     _uid_messages(pod_ok=False), _uid_messages(pod_message_id="wrong")):
        result = runner.inspect(messages, case)
        assert "target_event" not in result["evidence_keys"]
        assert "target_event_weak" in result["evidence_keys"]
        assert result["event_uid_mismatch"] == 0
        assert result["event_uid_unverified"] == 1
        assert not result["evidence_sufficient"]
    for name, namespace, kind in (("sample-noise", "kube-triage-demo", "Pod"),
                                  ("sample-c", "other-namespace", "Pod"),
                                  ("sample-c", "kube-triage-demo", "Node")):
        result = runner.inspect(_uid_messages(event_name=name,
                                              event_namespace=namespace,
                                              event_kind=kind), case)
        assert not any(key.startswith("target_event") for key in result["evidence_keys"])
        assert result["event_uid_mismatch"] == 0
        assert not result["evidence_sufficient"]
    invalid = runner.inspect(_uid_messages(event_uid=123), case)
    assert invalid["event_uid_invalid"] == 1
    assert "target_event" not in invalid["evidence_keys"]
    untrusted_pod = _uid_messages()
    pod_reply = json.loads(untrusted_pod[2]["content"])
    pod_reply["result"]["mock"] = False
    untrusted_pod[2]["content"] = json.dumps(pod_reply)
    result = runner.inspect(untrusted_pod, case)
    assert result["event_uid_unverified"] == 1
    assert "target_event" not in result["evidence_keys"]


def test_run_outcome_separates_protocol_and_quality():
    case = next(c for c in runner.load_cases(ROOT / "eval/issue12/blind-v1.json")
                if c["id"] == "c")
    end = [{"event": "end"}]
    good = runner.inspect(_uid_messages(), case)
    assert runner.run_outcome(good, "success", end, []) == ("success", False, "none")
    quality = runner.inspect([{"type": "ai", "name": "triage_llm",
                              "content": "证据不足"}], case)
    assert not quality["evidence_sufficient"]
    assert runner.run_outcome(quality, "success", end, []) == ("success", False, "none")
    unrelated = runner.inspect(_uid_messages(event_name="sample-noise"), case)
    assert not unrelated["evidence_sufficient"]
    assert runner.run_outcome(unrelated, "success", end, []) == ("success", False, "none")
    bad_cases = [
        (_uid_messages(pod_message_id="wrong"), "tool_id_mismatch"),
        (_uid_messages(pod_status="error"), "tool_message_failure"),
        (_uid_messages(pod_ok=False), "tool_message_failure"),
    ]
    missing_id = _uid_messages()
    missing_id[0]["tool_calls"][0]["id"] = ""
    bad_cases.append((missing_id, "tool_id_mismatch"))
    non_string_id = _uid_messages()
    non_string_id[0]["tool_calls"][0]["id"] = None
    bad_cases.append((non_string_id, "tool_id_mismatch"))
    duplicate = _uid_messages()
    duplicate[0]["tool_calls"][1]["id"] = "one"
    bad_cases.append((duplicate, "tool_id_mismatch"))
    for name, args in (("pods_delete", {"namespace": "kube-triage-demo"}),
                       ("events_list", {"namespace": "kube-system"}),
                       ("events_list", {"namespace": "kube-triage-demo", "extra": "x"})):
        messages = _uid_messages()
        messages[0]["tool_calls"][0].update({"name": name, "args": args})
        bad_cases.append((messages, "tool_policy_violation"))
    for messages, reason in bad_cases:
        assert runner.run_outcome(runner.inspect(messages, case), "success", end, []) == (
            "fail", True, reason)
    incompatible = _uid_messages()
    incompatible[-1]["content"] = "模型未返回内容或标准 Tool Call；本次诊断未完成。"
    assert runner.run_outcome(runner.inspect(incompatible, case), "success", end, [])[1]
    provider_failure = _uid_messages()
    provider_failure[-1]["content"] = "模型或 MCP 连接失败；本次诊断未完成。"
    assert runner.run_outcome(runner.inspect(provider_failure, case), "success", end, []) == (
        "fail", True, "model_or_mcp_failure")
    wrong_model = _uid_messages()
    wrong_model[-1]["response_metadata"] = {"model_name": "unexpected-model"}
    assert runner.run_outcome(runner.inspect(wrong_model, case), "success", end, []) == (
        "fail", True, "model_id_mismatch")
    assert runner.run_outcome(good, "failed", end, [])[1]
    assert runner.run_outcome(good, "success", [{"event": "error"}], [])[1]
    assert runner.run_outcome(good, "success", [], [])[1]
    assert runner.run_outcome(good, "success", end, ["pending"])[1]
    no_conclusion = _uid_messages()
    no_conclusion[-1]["content"] = ""
    assert runner.run_outcome(runner.inspect(no_conclusion, case), "success", end, [])[1]
    budget = _uid_messages()
    budget[-1]["content"] = "已达到本轮模型决策上限（4 轮）"
    assert runner.run_outcome(runner.inspect(budget, case), "success", end, []) == (
        "fail", False, "budget_exhausted")
    over_budget = runner.inspect(_uid_messages(), case)
    over_budget["budget_limit_exceeded"] = True
    assert runner.run_outcome(over_budget, "success", end, []) == (
        "fail", True, "budget_limit_violation")


def test_main_stops_after_protocol_failure_and_keeps_private_evidence(monkeypatch, tmp_path):
    output = tmp_path / "issue12-stop-test"
    monkeypatch.setattr(runner, "output_path", lambda _path: output)
    monkeypatch.setattr(runner, "read_env", lambda path: {
        "TRIAGE_ENV": "test", "TRIAGE_MOCK_DATASET": "issue12-blind-v1",
        "EVAL_PROMPT_VARIANT": "A" if str(path) == "a.env" else "B",
        "REPAIR_ENABLED": "false", "LLM_MODEL": "gpt-6-luna",
        "EVAL_LUNA_RESPONSES_HIGH": "true", "DEMO_API_TOKEN": "private-test-only",
        "LLM_API_KEY": "private-test-only", "LLM_BASE_URL": "http://localhost:9999"})
    calls = []
    messages = _uid_messages(pod_message_id="wrong")

    def fake_api(_base, _token, path, method="GET", body=None):
        calls.append(path)
        if path == "/threads":
            return {"thread_id": "thread-one"}
        if path.endswith("/state"):
            return {"values": {"messages": messages}, "next": []}
        if path.endswith("/history"):
            return []
        if path.endswith("/runs"):
            return [{"run_id": "run-one", "status": "success"}]
        raise AssertionError(path)

    monkeypatch.setattr(runner, "api", fake_api)
    monkeypatch.setattr(runner, "stream_run", lambda *_args: [{"event": "end"}])
    monkeypatch.setattr(sys, "argv", ["eval_issue12.py", "--out", str(output),
                                   "--env-file-a", "a.env", "--env-file-b", "b.env",
                                   "--authorize-model-send"])
    runner.main()
    assert calls.count("/threads") == 1
    rows = json.loads((output / "runs.json").read_text())
    report = json.loads((output / "summary.json").read_text())
    private = json.loads((output / "A-a-1-private.json").read_text())
    assert rows[0]["run_status"] == "fail" and rows[0]["stop_reason"] == "tool_id_mismatch"
    assert rows[0]["run_id"] == "run-one"
    assert report["attempted_total"] == 1 and report["not_run_total"] == 47
    assert report["A"]["not_run"] == 23 and report["B"]["not_run"] == 24
    assert private["thread_id"] == "thread-one" and private["state"]["values"]
    assert json.loads((output / "reviews.json").read_text())[0]["diagnosis_correct"] == "PENDING"


def test_stream_failure_recovers_read_only_evidence_without_retry(monkeypatch, tmp_path):
    output = tmp_path / "issue12-stream-stop"
    monkeypatch.setattr(runner, "output_path", lambda _path: output)
    monkeypatch.setattr(runner, "read_env", lambda path: {
        "TRIAGE_ENV": "test", "TRIAGE_MOCK_DATASET": "issue12-blind-v1",
        "EVAL_PROMPT_VARIANT": "A" if str(path) == "a.env" else "B",
        "REPAIR_ENABLED": "false", "LLM_MODEL": "gpt-6-luna",
        "EVAL_LUNA_RESPONSES_HIGH": "true", "DEMO_API_TOKEN": "private-test-only",
        "LLM_API_KEY": "private-test-only", "LLM_BASE_URL": "http://localhost:9999"})
    paths = []

    def fake_api(_base, _token, path, method="GET", body=None):
        paths.append(path)
        if path == "/threads":
            return {"thread_id": "thread-one"}
        if path.endswith("/state"):
            return {"values": {"messages": []}, "next": []}
        if path.endswith("/history"):
            return []
        if path.endswith("/runs"):
            return [{"run_id": "run-one", "status": "failed"}]
        raise AssertionError(path)

    def broken_stream(*_args):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(runner, "api", fake_api)
    monkeypatch.setattr(runner, "stream_run", broken_stream)
    monkeypatch.setattr(sys, "argv", ["eval_issue12.py", "--out", str(output),
                                   "--env-file-a", "a.env", "--env-file-b", "b.env",
                                   "--authorize-model-send"])
    runner.main()
    assert paths.count("/threads") == 1
    row = json.loads((output / "runs.json").read_text())[0]
    private = json.loads((output / "A-a-1-private.json").read_text())
    report = json.loads((output / "summary.json").read_text())
    assert row["run_status"] == "blocked" and row["run_id"] == "run-one"
    assert row["error_type"] == "TimeoutError"
    assert private["sse"] == "UNKNOWN" and private["state"]["values"]
    assert report["not_run_total"] == 47


def test_private_http_preflight_blocks_before_thread(monkeypatch, tmp_path):
    output = tmp_path / "issue12-http-block"
    monkeypatch.setattr(runner, "output_path", lambda _path: output)
    monkeypatch.setattr(runner, "read_env", lambda path: {
        "TRIAGE_ENV": "test", "TRIAGE_MOCK_DATASET": "issue12-blind-v1",
        "EVAL_PROMPT_VARIANT": "A" if str(path) == "a.env" else "B",
        "REPAIR_ENABLED": "false", "LLM_MODEL": "gpt-6-luna",
        "EVAL_LUNA_RESPONSES_HIGH": "true", "DEMO_API_TOKEN": "private-test-only",
        "LLM_API_KEY": "private-test-only", "LLM_BASE_URL": "http://192.168.1.20/v1"})
    monkeypatch.setattr(runner, "api", lambda *_args, **_kwargs: pytest.fail("API called"))
    monkeypatch.setattr(sys, "argv", ["eval_issue12.py", "--out", str(output),
                                   "--env-file-a", "a.env", "--env-file-b", "b.env",
                                   "--authorize-model-send"])
    with pytest.raises(SystemExit):
        runner.main()
    assert not output.exists()


def test_changed_blind_dataset_fails_before_dry_run_output(tmp_path):
    data = json.loads((ROOT / "eval/issue12/blind-v1.json").read_text())
    data["cases"][0]["question"] += " "
    changed = tmp_path / "changed-blind.json"
    changed.write_text(json.dumps(data, ensure_ascii=False))
    output = ".local/eval-runs/issue12-changed-data-plan"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/eval_issue12.py"),
                             "--cases", str(changed), "--out", output, "--dry-run"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode != 0 and "Frozen dataset" in result.stderr
    assert not (ROOT / output).exists()
