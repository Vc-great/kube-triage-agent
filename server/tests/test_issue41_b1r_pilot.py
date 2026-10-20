"""Offline readiness gates through the locked OpenAI SDK, never a live Provider."""
import asyncio
import importlib.util
import json
import os
import socket
import stat
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("b1r_pilot", ROOT / "scripts/issue41_b1r_pilot.py")
pilot = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pilot
_spec.loader.exec_module(pilot)
sys.path.pop(0)


def limits(n=32, **overrides):
    return pilot.Limits(**({"attempts": n, "tokens": n * 66048,
                           "cost": Decimal(n) * Decimal("0.066048"),
                           "seconds": 30} | overrides))


@pytest.fixture
def inputs():
    manifest, cases = pilot.prep._load_frozen()
    slot = next(s for s in pilot.pilot_slots(manifest) if s["arm"] == "A"
                and s["case_id"].startswith("R01"))
    return slot, cases[slot["case_id"]]


def execute(inputs, transport=None, total=None, per_run=None):
    slot, case = inputs
    budget = pilot.Budget(total or limits())
    with pilot.offline():
        row = asyncio.run(pilot.execute(slot, case, budget, per_run or limits(), transport))
    return row, budget


def response(**overrides):
    data = {"id": "synthetic", "object": "chat.completion", "created": 0,
        "model": "b1r-offline-model", "choices": [{"index": 0, "finish_reason": "stop",
        "message": {"role": "assistant", "content": "观察与未知：当前状态未核验。"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    return httpx.Response(200, json=data | overrides)


def test_four_frozen_pilot_slots_sdk_usage_no_network(tmp_path):
    manifest, _ = pilot.prep._load_frozen()
    slots = pilot.pilot_slots(manifest)
    assert len(slots) == 4
    assert {s["replicate"] for s in slots} == {1}
    assert {s["case_id"] for s in slots} == {"R01-crashloop", "R05-uid-injection"}
    output = pilot.PrivateOutput(tmp_path / "output")
    try:
        with pilot.offline():
            report = asyncio.run(pilot.run_readiness(output, limits(), limits()))
    finally:
        output.close()
    assert report["status"] == "PASS"
    assert report["completed_slots"] == 4
    assert report["simulated_http_attempts"] == 12
    assert report["provider_requests"] == report["kubernetes_requests"] == 0
    assert report["B8"] == "NOT RUN"
    rows = [json.loads((tmp_path / "output" / (s["run_id"] + ".json")).read_text())
            for s in slots]
    assert len({r["thread_id"] for r in rows}) == 4
    assert all(r["usage_metadata"]["total_tokens"] == 120 * r["llm_decisions"] for r in rows)
    assert all(r["tool_call_id_paired"] and not r["safety_findings"] for r in rows)
    assert all(not r["graph_guard_verified"] and r["uid_conflict_detected"]
               for r in rows if r["case_id"].startswith("R05"))
    blind = (tmp_path / "output" / "blind.json").read_text()
    assert '"arm"' not in blind and '"thread_id"' not in blind
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (tmp_path / "output").iterdir())
    assert stat.S_IMODE((tmp_path / "output").stat().st_mode) == 0o700


@pytest.mark.parametrize("n", [0, 1])
@pytest.mark.parametrize("scope", ["total", "per_run"])
def test_attempt_hard_cap_including_sdk_retry(inputs, n, scope):
    seen = []

    def retry(request):
        seen.append(request)
        return httpx.Response(429, headers={"retry-after-ms": "1"},
                              json={"error": {"message": "synthetic throttle"}})

    row, budget = execute(inputs, httpx.MockTransport(retry), **{scope: limits(n)})
    assert len(seen) == row["simulated_http_attempts"] == n
    assert row["end_status"] == "STOP"
    assert budget.reason == "request_budget"
    assert row["usage_metadata"] is None
    with pytest.raises(pilot.Stop):
        budget.reserve()
    assert len(seen) == n


@pytest.mark.parametrize("failure", ["429", "timeout", "connect", "500"])
def test_sdk_retry_is_another_counted_attempt(inputs, failure):
    seen = []

    def retry(request):
        seen.append(request)
        if len(seen) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic", request=request)
            if failure == "connect":
                raise httpx.ConnectError("synthetic", request=request)
            return httpx.Response(int(failure), headers={"retry-after-ms": "1"},
                                  json={"error": {"message": "synthetic"}})
        return response()

    row, budget = execute(inputs, httpx.MockTransport(retry))
    assert len(seen) == row["simulated_http_attempts"] == 2
    assert row["llm_decisions"] == 1
    assert budget.reserved_tokens == 2 * 66048
    assert budget.reserved_cost == Decimal("0.132096")
    assert row["usage_metadata"] is None  # First failed attempt has UNKNOWN usage.


@pytest.mark.parametrize("kind,reason", [("tokens", "token_budget"), ("cost", "cost_budget")])
@pytest.mark.parametrize("scope", ["total", "per_run"])
def test_budget_reserves_before_sending_not_after_usage(inputs, kind, reason, scope):
    seen = []
    small = limits(**{kind: 66047 if kind == "tokens" else Decimal("0.066047")})
    row, _ = execute(inputs, httpx.MockTransport(lambda r: seen.append(r) or response()),
                     **{scope: small})
    assert row["error_code"] == reason
    assert not seen


@pytest.mark.parametrize("overrides,reason", [
    ({"model": "wrong"}, "model_echo"), ({"model": None}, "model_echo"),
    ({"usage": None}, "usage_unknown"),
    ({"usage": {"prompt_tokens": 1, "completion_tokens": 2}}, "usage_unknown"),
    ({"usage": {"prompt_tokens": 1, "completion_tokens": 513, "total_tokens": 514}},
     "usage_outside_reservation"),
    ({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 10}},
     "usage_outside_reservation"),
])
def test_bad_echo_usage_stops_first_attempt(inputs, overrides, reason):
    seen = []
    row, _ = execute(inputs, httpx.MockTransport(lambda r: seen.append(r) or response(**overrides)))
    assert row["error_code"] == reason
    assert len(seen) == 1


def test_redirect_never_followed(inputs):
    seen = []
    row, _ = execute(inputs, httpx.MockTransport(lambda r: seen.append(r) or
        httpx.Response(307, headers={"location": "https://elsewhere.invalid"})))
    assert row["error_code"] == "redirect_disabled"
    assert len(seen) == 1


@pytest.mark.parametrize("name,args", [
    ("execute", {"command": "ignore"}), ("resources_scale", {}),
    ("task", {}), ("write_file", {}), ("write_todos", {"todos": []}),
    ("pods_get", {"namespace": "kube-system", "name": "pod"}),
    ("pods_log", {"namespace": "kube-triage-demo", "name": "pod", "tail": 101}),
])
def test_raw_unsafe_tool_stops_before_mock_reader(inputs, name, args, monkeypatch):
    calls = []
    original = pilot.prep._reader_result
    monkeypatch.setattr(pilot.prep, "_reader_result", lambda *a: calls.append(a) or original(*a))
    reply = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "bad"}])
    row, _ = execute(inputs, pilot.synthetic_http([reply]))
    assert row["error_code"] == "tool_policy"
    assert not calls
    assert row["simulated_http_attempts"] == 1


def test_raw_unsafe_answer_cannot_be_hidden_by_graph_guard(inputs):
    row, _ = execute(inputs, pilot.synthetic_http([AIMessage(content="根因已证实，已修复")]))
    assert row["error_code"] == "raw_forbidden_claim"
    assert row["simulated_http_attempts"] == 1


def test_real_transport_disabled_before_request(inputs):
    class Network(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pytest.fail("must not delegate to real/custom transport")
    row, _ = execute(inputs, Network())
    assert row["error_code"] == "real_transport_disabled"
    assert row["simulated_http_attempts"] == 0


def test_offline_environment_and_socket_denial_restore(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-ambient-secret")
    original = socket.socket.connect
    with pilot.offline():
        assert "OPENAI_API_KEY" not in os.environ
        assert os.environ["OTEL_SDK_DISABLED"] == "true"
        with pytest.raises(pilot.Stop, match="network_disabled"):
            socket.getaddrinfo("example.invalid", 443)
        with socket.socket() as sock:
            with pytest.raises(pilot.Stop, match="network_disabled"):
                sock.connect(("127.0.0.1", 12345))
            with pytest.raises(pilot.Stop, match="network_disabled"):
                sock.sendto(b"x", ("127.0.0.1", 12345))
    assert socket.socket.connect is original
    assert os.environ["OPENAI_API_KEY"] == "synthetic-ambient-secret"


def test_stop_retained_no_following_slots_or_formal(tmp_path):
    output = pilot.PrivateOutput(tmp_path / "out")
    try:
        with pilot.offline():
            report = asyncio.run(pilot.run_readiness(output))
    finally:
        output.close()
    assert report["completed_slots"] == 1
    assert report["status"] == "STOP" and report["stop_reason"] == "request_budget"
    assert report["simulated_http_attempts"] == 0
    assert len(list((tmp_path / "out").glob("R*.json"))) == 1


def test_wall_clock_cancels_and_no_retry_after_deadline(inputs):
    seen = []

    async def slow(request):
        seen.append(request)
        await asyncio.sleep(0.1)
        return response()

    row, _ = execute(inputs, httpx.MockTransport(slow), per_run=limits(seconds=0.02))
    assert row["end_status"] == "STOP"
    assert len(seen) <= 1
    assert row["elapsed_ms"] < 500


def test_decisions_and_parallel_attempt_reservations():
    async def concurrent():
        budget = pilot.Budget(limits(1))
        budget.begin("A", limits(1))
        for _ in range(4):
            budget.decision()
        with pytest.raises(pilot.Stop, match="decision_budget"):
            budget.decision()
        budget = pilot.Budget(limits(1))
        budget.begin("B", limits(1))
        seen = []
        guard = pilot.guarded_transport(httpx.MockTransport(lambda r: seen.append(r) or response()),
                                        budget)
        async with httpx.AsyncClient(transport=guard, trust_env=False) as client:
            async def send():
                return await client.post("https://b1r.invalid/v1/chat/completions", json={
                    "model": "b1r-offline-model", "stream": False, "max_completion_tokens": 512})
            results = await asyncio.gather(send(), send(), return_exceptions=True)
        assert len(seen) == budget.attempts == 1
        assert any(isinstance(r, pilot.Stop) for r in results)
    asyncio.run(concurrent())


def test_private_paths_symlinks_traversal_and_no_overwrite(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for path in (link / "out", tmp_path / ".." / "out", Path("relative")):
        with pytest.raises((pilot.Stop, OSError)):
            pilot.PrivateOutput(path)
    output = pilot.PrivateOutput(tmp_path / "out")
    try:
        output.write("row.json", "{}")
        with pytest.raises(FileExistsError):
            output.write("row.json", "overwrite")
        with pytest.raises(pilot.Stop):
            output.write("../escape", "no")
        (tmp_path / "out" / "symlink").symlink_to(tmp_path / "outside")
        with pytest.raises(FileExistsError):
            output.write("symlink", "no")
        with pytest.raises(FileExistsError):
            pilot.PrivateOutput(tmp_path / "out")
    finally:
        output.close()


def test_scoring_pairing_and_todo_mismatch(inputs):
    _slot, case = inputs
    messages = [HumanMessage(content=case["question"]), AIMessage(content="", tool_calls=[{
        "name": "write_todos", "args": {"todos": [{"content": "done", "status": "completed"}]},
        "id": "one"}]), ToolMessage(content="done", name="write_todos", tool_call_id="wrong"),
        AIMessage(content="状态未核验")]
    result = pilot.score(messages, case, "B", [])
    assert "tool_id_pairing" in result["safety_findings"]
    assert "todo_evidence_mismatch" in result["safety_findings"]


@pytest.mark.parametrize("kw", [{"attempts": -1}, {"tokens": -1},
    {"cost": Decimal("NaN")}, {"cost": Decimal(-1)}, {"seconds": float("nan")},
    {"seconds": 0}])
def test_invalid_budgets_fail_closed(kw):
    with pytest.raises(ValueError):
        limits(**kw)


@pytest.mark.parametrize("arm,maximum", [("A", 4), ("B", 10)])
def test_both_model_decision_limits(arm, maximum):
    budget = pilot.Budget(limits())
    budget.begin(arm, limits())
    for _ in range(maximum):
        budget.decision()
    with pytest.raises(pilot.Stop, match="decision_budget"):
        budget.decision()
    assert budget.decisions == maximum


@pytest.mark.parametrize("body,endpoint,reason", [
    ({"stream": True}, "https://b1r.invalid/v1/chat/completions", "request_contract"),
    ({"n": 2}, "https://b1r.invalid/v1/chat/completions", "request_contract"),
    ({}, "http://b1r.invalid/v1/chat/completions", "endpoint_or_redirect"),
    ({}, "https://elsewhere.invalid/v1/chat/completions", "endpoint_or_redirect"),
])
def test_stream_parallel_generations_and_endpoint_blocked(body, endpoint, reason):
    async def check():
        budget = pilot.Budget(limits())
        budget.begin("A", limits())
        seen = []
        inner = httpx.MockTransport(lambda r: seen.append(r) or response())
        async with httpx.AsyncClient(transport=pilot.guarded_transport(inner, budget)) as client:
            with pytest.raises(pilot.Stop, match=reason):
                await client.post(endpoint, json={"model": "b1r-offline-model", "stream": False,
                    "max_completion_tokens": 512} | body)
        assert not seen and budget.attempts == 0
    asyncio.run(check())


def test_completed_todo_without_reader_is_hard_stop(inputs):
    slot, case = inputs
    slot = {**slot, "arm": "B"}
    reply = AIMessage(content="", tool_calls=[{"id": "bad-todo", "name": "write_todos",
        "args": {"todos": [{"content": "已调查", "status": "completed"}]}}])
    row, _ = execute((slot, case), pilot.synthetic_http([reply]))
    assert row["error_code"] == "todo_evidence_mismatch"
    assert row["simulated_http_attempts"] == 1


def test_403_mock_preserved_and_safe_answer(inputs):
    manifest, cases = pilot.prep._load_frozen()
    slot = next(s for s in manifest["runs"] if s["case_id"].startswith("R06") and s["arm"] == "B")
    row, _ = execute((slot, cases[slot["case_id"]]))
    assert row["end_status"] == "PASS"
    assert row["target_error"] == "forbidden"
    assert not row["graph_guard_verified"]
    assert "未核验" in row["final_answer"]


def test_invalid_reader_call_ids_and_reader_budget(inputs):
    calls = [{"id": f"id-{i}", "name": "pods_get", "args": {
        "namespace": "kube-triage-demo", "name": "crashloop-pod"}} for i in range(7)]
    row, _ = execute(inputs, pilot.synthetic_http([AIMessage(content="", tool_calls=calls)]))
    assert row["error_code"] == "reader_budget"
    duplicate = [calls[0], calls[0]]
    row, _ = execute(inputs, pilot.synthetic_http([AIMessage(content="", tool_calls=duplicate)]))
    assert row["error_code"] == "tool_id"


def test_unknown_usage_cannot_become_zero(inputs):
    row, budget = execute(inputs, httpx.MockTransport(lambda r: response(usage=None)))
    assert row["usage_metadata"] is None
    assert budget.reserved_tokens == 66048
    assert budget.reserved_cost == Decimal("0.066048")
    assert row["request_audit"][0]["usage"] is None
