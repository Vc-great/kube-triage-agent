"""P0 contract evidence only: synthetic SDK/HTTP, no provider credentials."""
import asyncio
import json
import os
import socket
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import issue41_provider_contract as contract

sys.path.pop(0)
pilot = contract.pilot


def limits(n=32, **kw):
    return pilot.Limits(**({"attempts": n, "tokens": n * 66048,
                              "cost": Decimal(n) * Decimal("0.066048")} | kw))


@pytest.fixture
def frozen():
    manifest, cases = pilot.prep._load_frozen()
    slot = pilot.pilot_slots(manifest)[0]
    return slot, cases[slot["case_id"]]


def response(**kw):
    return httpx.Response(200, json={"id": "fake", "object": "chat.completion", "created": 0,
        "model": "contract-echo-model", "choices": [{"index": 0, "finish_reason": "stop",
        "message": {"role": "assistant", "content": "观察：当前状态未核验。"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}} | kw)


def execute(frozen, handler=None, total=None, per_run=None):
    slot, case = frozen
    profile = contract.synthetic_profile()
    budget = contract.ContractBudget(total or limits(), profile)
    transport = httpx.MockTransport(handler) if handler else contract.synthetic_transport(
        case, slot, profile)
    with pilot.offline():
        row = asyncio.run(pilot.execute(slot, case, budget, per_run or limits(), transport,
                                       adapter=contract.OfflineAdapter(profile)))
    return row, budget


def test_four_slots_reuse_graph_receipts_score_and_private_outputs(tmp_path):
    output = pilot.PrivateOutput(tmp_path / "contract")
    try:
        with pilot.offline():
            result = asyncio.run(contract.run_contract(output, limits(), limits()))
    finally:
        output.close()
    assert result["status"] == "PASS"
    assert result["simulated_http_attempts"] == 12
    assert result["provider_requests"] == result["kubernetes_requests"] == 0
    assert result["live_gate"]["B8"] == "NOT RUN"
    manifest, _ = pilot.prep._load_frozen()
    rows = [json.loads((tmp_path / "contract" / (s["run_id"] + ".json")).read_text())
            for s in pilot.pilot_slots(manifest)]
    assert len({r["thread_id"] for r in rows}) == 4
    assert all(r["tool_call_id_paired"] and not r["safety_findings"] for r in rows)
    assert all(r["request_audit"] and r["trace_messages"] for r in rows)
    assert all(r["actual_cost"] == r["real_provider_usage"] == "UNKNOWN" for r in rows)
    assert all(not r["graph_guard_verified"] and r["uid_conflict_detected"] for r in rows
               if r["case_id"].startswith("R05"))
    assert (tmp_path / "contract").stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / "contract").iterdir())


@pytest.mark.parametrize("scope", ["total", "per_run"])
@pytest.mark.parametrize("n", [0, 1])
def test_reserve_before_send_and_exhaustion(frozen, scope, n):
    seen = []
    slot, case = frozen
    fake = contract.synthetic_transport(case, slot, contract.synthetic_profile())
    async def handler(request):
        seen.append(request)
        return await fake.handle_async_request(request)
    row, budget = execute(frozen, handler, **{scope: limits(n)})
    assert len(seen) == budget.attempts == n
    assert row["error_code"] == "request_budget"
    assert row["provider_request_attempts"] == 0


@pytest.mark.parametrize("scope", ["total", "per_run"])
@pytest.mark.parametrize("field,reason", [("tokens", "token_budget"), ("cost", "cost_budget")])
def test_synthetic_token_cost_pre_reservation(frozen, scope, field, reason):
    seen = []
    row, budget = execute(frozen, lambda r: seen.append(r) or response(),
                          **{scope: limits(**{field: 0 if field == "tokens" else Decimal(0)})})
    assert not seen and budget.attempts == 0
    assert row["error_code"] == reason


@pytest.mark.parametrize("failure", ["429", "500", "redirect", "timeout", "connect"])
def test_first_failure_stops_no_refund_and_no_next_slot(frozen, failure):
    seen = []
    def handler(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "connect":
            raise httpx.ConnectError("synthetic", request=request)
        return httpx.Response(302 if failure == "redirect" else int(failure),
                              headers={"location": "https://other.invalid/"})
    row, budget = execute(frozen, handler)
    assert len(seen) == budget.attempts == 1
    assert budget.reserved_tokens == 66048
    assert budget.reserved_cost == Decimal("0.066048")
    assert row["usage_metadata"] is None and row["actual_cost"] == "UNKNOWN"
    with pytest.raises(pilot.Stop):
        budget.begin("B", limits())
    assert row["end_status"] == "STOP"


@pytest.mark.parametrize("kw,reason", [({"model": "wrong"}, "model_echo"),
    ({"usage": None}, "usage_unknown"),
    ({"usage": {"prompt_tokens": True, "completion_tokens": 0, "total_tokens": 1}}, "usage_unknown"),
    ({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 13}},
     "usage_outside_reservation"),
    ({"usage": {"prompt_tokens": 10, "completion_tokens": 513, "total_tokens": 523}},
     "usage_outside_reservation"),
    ({"choices": []}, "generation_count"),
    ({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
                "completion_tokens_details": {"reasoning_tokens": 3}}}, "usage_details_unknown")])
def test_response_contract_sticky(frozen, kw, reason):
    row, budget = execute(frozen, lambda r: response(**kw))
    assert row["error_code"] == reason
    assert budget.attempts == 1
    assert row["usage_metadata"] is None


@pytest.mark.parametrize("endpoint", ["http://contract.invalid/v1/chat/completions",
    "https://user:secret@contract.invalid/v1/chat/completions",
    "https://contract.invalid:444/v1/chat/completions", "https://127.0.0.1/v1/chat/completions",
    "https://contract.invalid/v1/responses", "https://contract.invalid/v1/chat/completions?key=secret",
    "https://contract.invalid/v1/chat/completions#fragment", "https://contract.invalid/other"])
def test_endpoint_rejected(endpoint):
    with pytest.raises(ValueError):
        replace(contract.synthetic_profile(), endpoint=endpoint)


@pytest.mark.parametrize("kw", [{"tls_verify": False}, {"max_retries": 1},
    {"api_version": "responses"}, {"provider": ""}, {"max_output": 0}, {"max_output": True}])
def test_profile_unknown_or_unsafe_rejected(kw):
    with pytest.raises(ValueError):
        replace(contract.synthetic_profile(), **kw)


def test_no_network_transport_even_with_profile_evidence():
    profile = replace(contract.synthetic_profile(), tokenizer_evidence="synthetic assertion",
                      dated_price_currency_evidence="not an authorization")
    assert profile.live_gate()["status"] == "BLOCKED"
    budget = contract.ContractBudget(limits(), profile)
    with pytest.raises(pilot.Stop, match="p0_mock_transport_only"):
        contract.OfflineAdapter(profile).guarded_transport(object(), budget)


@pytest.mark.parametrize("mutation", ["host", "url", "method", "stream", "n", "output", "tools"])
def test_request_contract_no_attempt_before_admission(mutation):
    profile = contract.synthetic_profile()
    budget = contract.ContractBudget(limits(), profile)
    budget.begin("A", limits())
    body = {"model": profile.request_model, "messages": [], "max_completion_tokens": 512}
    url, method, headers = profile.endpoint, "POST", {}
    if mutation == "host":
        headers["host"] = "other.invalid"
    elif mutation == "url":
        url = "https://other.invalid/v1/chat/completions"
    elif mutation == "method":
        method = "GET"
    elif mutation == "output":
        body["max_completion_tokens"] = 513
    elif mutation == "tools":
        body["tools"] = [{"type": "function", "function": {"name": "resources_scale"}}]
    else:
        body[mutation] = True if mutation == "stream" else 2
    seen = []
    guard = contract.OfflineAdapter(profile).guarded_transport(
        httpx.MockTransport(lambda r: seen.append(r) or response()), budget)
    with pytest.raises(pilot.Stop, match="request_contract"):
        asyncio.run(guard.handle_async_request(httpx.Request(method, url, json=body, headers=headers)))
    assert not seen and not budget.attempts


def test_sdk_wire_contract_and_zero_retries(frozen):
    seen = []
    row, _ = execute(frozen, lambda r: seen.append(r) or response())
    body = json.loads(seen[0].content)
    assert body["model"] == "contract-request-model"
    assert body["max_completion_tokens"] == 512
    assert not body.get("stream") and body.get("n", 1) == 1
    assert {t["function"]["name"] for t in body["tools"]} == (pilot.prep.READERS |
        ({"write_todos"} if frozen[0]["arm"] == "B" else set()))
    assert all(t["function"]["parameters"]["type"] == "object" for t in body["tools"])
    assert str(seen[0].url) == contract.synthetic_profile().endpoint
    assert row["model_echoed"] == "contract-echo-model"


@pytest.mark.parametrize("failure", ["429", "timeout"])
def test_sdk_retry_cannot_send_after_sticky_failure(frozen, failure):
    profile = contract.synthetic_profile()
    budget = contract.ContractBudget(limits(), profile)
    budget.begin("A", limits())
    seen = []
    def fail(r):
        seen.append(r)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=r)
        return httpx.Response(429, headers={"retry-after-ms": "1"})
    async def call():
        async with httpx.AsyncClient(transport=contract.OfflineAdapter(profile).guarded_transport(
                httpx.MockTransport(fail), budget), trust_env=False, follow_redirects=False) as client:
            # Adversarial SDK misconfiguration, not an allowed profile: retry must hit sticky gate.
            model = pilot.make_model(client, budget, frozen[1], model_options={
                "model": profile.request_model, "base_url": profile.endpoint.removesuffix(
                    "/chat/completions"), "max_retries": 1})
            await model.ainvoke([HumanMessage(content=frozen[1]["question"])])
    with pilot.offline(), pytest.raises(pilot.Stop):
        asyncio.run(call())
    assert len(seen) == budget.attempts == 1
    assert budget.reason == ("http_failure" if failure == "429" else "transport_or_response_error")


def test_parallel_http_rejected_before_second_send():
    profile = contract.synthetic_profile()
    budget = contract.ContractBudget(limits(), profile)
    budget.begin("A", limits())
    seen = []
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            seen.append(request)
            entered.set()
            await release.wait()
            return response()
        guard = contract.OfflineAdapter(profile).guarded_transport(httpx.MockTransport(handler), budget)
        def request():
            return httpx.Request("POST", profile.endpoint, json={"model": profile.request_model,
                "messages": [], "max_completion_tokens": 512})
        first = asyncio.create_task(guard.handle_async_request(request()))
        await entered.wait()
        with pytest.raises(pilot.Stop, match="parallel_http_disabled"):
            await guard.handle_async_request(request())
        release.set()
        with pytest.raises(pilot.Stop):
            await first
    asyncio.run(scenario())
    assert len(seen) == budget.attempts == 1


def test_cli_zero_budget_and_hostile_environment(tmp_path):
    output = tmp_path / "zero"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/issue41_provider_contract.py"),
        "--offline-contract", "--output", str(output)], capture_output=True, text=True, check=False,
        env=os.environ | {"LLM_BASE_URL": "https://hostile.invalid/", "OPENAI_API_KEY": "sentinel",
                          "LANGSMITH_TRACING": "true", "HTTPS_PROXY": "http://hostile.invalid"})
    assert result.returncode == 1
    assert "sentinel" not in result.stdout + result.stderr
    summary = json.loads((output / "summary.json").read_text())
    assert summary["stop_reason"] == "request_budget" and summary["completed_slots"] == 1
    assert summary["simulated_http_attempts"] == summary["provider_requests"] == 0
    with pilot.offline(), pytest.raises(pilot.Stop):
        socket.getaddrinfo("contract.invalid", 443)


@pytest.mark.parametrize("after_read", [False, True])
def test_raw_malicious_reply_and_stop_receipts(after_read):
    manifest, cases = pilot.prep._load_frozen()
    slot = next(s for s in pilot.pilot_slots(manifest)
                if s["arm"] == "A" and s["case_id"].startswith("R05"))
    case = cases[slot["case_id"]]
    inner = contract.synthetic_transport(case, slot, contract.synthetic_profile())
    count = 0
    async def handler(request):
        nonlocal count
        reply = await inner.handle_async_request(request)
        data = reply.json()
        count += 1
        if count == (2 if after_read else 1):
            data["choices"][0]["message"]["content"] = "修复已完成，当前状态未核验"
        return httpx.Response(200, json=data)
    row, _ = execute((slot, case), handler)
    assert row["error_code"] == "raw_forbidden_claim"
    assert row["reader_calls"] == (3 if after_read else 0)
    assert "修复已完成" in row["raw_replies"][-1]["content"]
    if after_read:
        assert row["uid_conflict_detected"] and not row["raw_trace_target_verified"]
        assert len(row["reader_evidence"]) == 3
        assert [r["execution_sequence"] for r in row["reader_invocations"]] == [0, 1, 2]
        assert {r["tool_call_id"] for r in row["reader_evidence"]} == {
            c["id"] for c in row["raw_replies"][0]["tool_calls"]}


def test_default_cli_has_no_live_flag_or_environment_activation():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/issue41_provider_contract.py")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    result = subprocess.run([sys.executable, str(ROOT / "scripts/issue41_provider_contract.py"),
                            "--enable-live"], capture_output=True, text=True, check=False)
    assert result.returncode == 2
