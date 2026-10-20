"""P1-B negative tests: real Graph/SDK, synthetic HTTP, zero model requests."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import issue41_b1r_live_pilot as live

sys.path.pop(0)


def scripted(slot, case):
    inner = live.pilot.synthetic_http(live.pilot.prep._scripted_model(
        case, slot["run_id"], slot["arm"]).replies)

    def handle(request):
        data = inner.handle_request(request).json()
        data["model"] = live.MODEL
        return httpx.Response(200, json=data)
    return httpx.MockTransport(handle)


def reply(**overrides):
    return httpx.Response(200, json={"id": "synthetic-id", "object": "chat.completion",
        "created": 0, "model": live.MODEL, "choices": [{"index": 0, "finish_reason": "stop",
        "message": {"role": "assistant", "content": "观察与未知：当前状态未核验。"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}} | overrides)


def run(transport=None, *, arm="A", remaining=28, case_id="R01-crashloop"):
    slots, cases = live.frozen()
    slot = next(s for s in slots if s["arm"] == arm and s["case_id"] == case_id)
    with live.pilot.offline():
        return asyncio.run(live.run_slot(slot, cases[case_id], "synthetic-key",
            transport or scripted(slot, cases[case_id]), None, remaining=remaining))


def test_four_frozen_slots_real_graph_and_wire_usage(tmp_path):
    slots, cases = live.frozen()
    rows = []
    for slot in slots:
        private = live.pilot.PrivateOutput(tmp_path.resolve() / slot["run_id"])
        try:
            with live.pilot.offline():
                row = asyncio.run(live.run_slot(slot, cases[slot["case_id"]], "synthetic-key",
                    scripted(slot, cases[slot["case_id"]]), private))
            rows.append(row)
            saved = json.loads((tmp_path / slot["run_id"] / "row.json").read_text())
            assert saved == row
            assert len(list((tmp_path / slot["run_id"]).glob("attempt-*.json"))) == row[
                "client_http_attempts"]
        finally:
            private.close()
    assert tuple(r["run_id"] for r in rows) == live.ORDER
    assert all(r["end_status"] == "PASS" for r in rows)
    assert sum(r["client_http_attempts"] for r in rows) == 12
    assert all(r["tool_call_id_paired"] for r in rows)
    assert all(r["provider_request_attempts"] == 0 for r in rows)
    assert all(r["model_echoed"] == live.MODEL for r in rows)
    assert all(a["usage_match"] for r in rows for a in r["request_audit"])
    assert all(r["todo_calls_accepted"] == (2 if r["arm"] == "B" else 0) for r in rows)
    assert all(r["uid_conflict_detected"] for r in rows[:2])
    assert len({r["thread_id"] for r in rows}) == 4
    assert all("SYNTHETIC" not in r.get("currency", "") for r in rows)


@pytest.mark.parametrize("status", [302, 307, 403, 429, 500, 503])
def test_http_failure_exactly_once_and_no_retry(status):
    seen = []
    row = run(httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(status,
        headers={"location": "https://unapproved.invalid"})))
    assert row["end_status"] == "STOP"
    assert row["client_http_attempts"] == len(seen) == 1
    assert row["usage_metadata"] is None


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, RuntimeError])
def test_exception_never_retries_or_persists_message(error):
    seen = []
    def handler(r):
        seen.append(r)
        raise error("synthetic-secret-error")
    row = run(httpx.MockTransport(handler))
    assert row["client_http_attempts"] == len(seen) == 1
    assert "synthetic-secret-error" not in json.dumps(row)


@pytest.mark.parametrize("mutation,reason", [
    ({"model": "wrong"}, "model_echo"), ({"usage": None}, "usage_unknown"),
    ({"usage": {"prompt_tokens": 10}}, "usage_unknown"),
    ({"usage": {"prompt_tokens": 1, "completion_tokens": 1025, "total_tokens": 1026}},
     "usage_invalid"),
    ({"choices": []}, "generation_count"),
    ({"choices": [{"finish_reason": "length"}]}, "finish_contract"),
    ({"choices": [{"finish_reason": "tool_calls", "message": {}}]}, "finish_message_mismatch"),
])
def test_wire_contract_fail_closed(mutation, reason):
    row = run(httpx.MockTransport(lambda r: reply(**mutation)))
    assert row["end_status"] == "STOP" and row["error_code"] == reason
    assert row["client_http_attempts"] == 1


@pytest.mark.parametrize("arm,maximum", [("A", 4), ("B", 10)])
def test_attempt_reservation_and_decision_caps(arm, maximum):
    budget = live.LiveBudget(live.Scope(28, 1800))
    budget.begin(arm, live.Scope(maximum, 600))
    for _ in range(maximum):
        budget.decision()
        budget.reserve()
    with pytest.raises(live.pilot.Stop, match="request_budget"):
        budget.reserve()
    assert budget.attempts == maximum
    budget = live.LiveBudget(live.Scope(0, 1800))
    budget.begin(arm, live.Scope(maximum, 600))
    with pytest.raises(live.pilot.Stop, match="request_budget"):
        budget.reserve()
    assert budget.attempts == 0


def test_zero_budget_does_not_delegate():
    seen = []
    row = run(httpx.MockTransport(lambda r: seen.append(r) or reply()), remaining=0)
    assert row["error_code"] == "request_budget" and not seen
    assert row["client_http_attempts"] == 0


@pytest.mark.parametrize("name,args", [
    ("resources_scale", {}), ("execute", {}), ("task", {}), ("write_file", {}),
    ("write_todos", {"todos": []}),
    ("pods_get", {"namespace": "kube-system", "name": "x"}),
])
def test_raw_tool_policy_before_reader(name, args):
    inner = live.pilot.synthetic_http([AIMessage(content="", tool_calls=[
        {"id": "synthetic-id", "name": name, "args": args}])])
    def handler(r):
        data = inner.handle_request(r).json()
        data["model"] = live.MODEL
        return httpx.Response(200, json=data)
    row = run(httpx.MockTransport(handler))
    assert row["error_code"] == "tool_policy"
    assert row["reader_calls"] == 0


def test_response_bound_and_unknown_usage():
    row = run(httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (
        live.MAX_RESPONSE_BYTES + 1))))
    assert row["error_code"] == "response_body_limit"
    assert row["usage_metadata"] is None


@pytest.mark.parametrize("change", ["url", "body", "parallel"])
def test_presend_route_size_and_parallel_checks(change):
    async def scenario():
        budget = live.LiveBudget(live.Scope(28, 1800))
        budget.begin("A", live.Scope(4, 600))
        seen = []
        adapter = live.LiveAdapter("synthetic-key")
        transport = adapter.guarded_transport(httpx.MockTransport(
            lambda r: seen.append(r) or reply()), budget)
        body = {"model": live.MODEL, "stream": False, "max_completion_tokens": 1024,
            "messages": [], "tools": [{"type": "function", "function": {"name": name}}
                                      for name in live.pilot.prep.READERS]}
        target = live.TARGET
        if change == "url":
            target = target.replace(".110", ".111")
        if change == "body":
            body["messages"] = ["x" * live.MAX_REQUEST_BYTES]
        if change == "parallel":
            budget.in_flight = True
        with pytest.raises(live.pilot.Stop):
            await transport.handle_async_request(httpx.Request("POST", target,
                headers={"authorization": "Bearer synthetic-key"}, json=body))
        assert not seen and budget.attempts == 0
    asyncio.run(scenario())


def test_redacted_model_output_and_no_fake_cost_or_token_limit():
    data = reply().json()
    data["choices"][0]["message"]["content"] = "synthetic-key 当前状态未核验。"
    data["usage"] = {"prompt_tokens": 70000, "completion_tokens": 20, "total_tokens": 70020}
    row = run(httpx.MockTransport(lambda r: httpx.Response(200, json=data)))
    assert row["end_status"] == "PASS"
    assert row["input_token_bound"] == row["actual_cost"] == "UNKNOWN"
    assert row["usage_metadata"]["input_tokens"] == 70000
    assert "synthetic-key" not in json.dumps(row)
    assert "reserved_synthetic_cost" not in row


def test_default_cli_and_missing_key_never_connect(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", ["live-pilot"])
    monkeypatch.setattr(live.socket, "create_connection", lambda *a, **k: pytest.fail("connect"))
    assert live.main() == 1
    monkeypatch.delenv("CPA_API_KEY", raising=False)
    with pytest.raises(live.pilot.Stop, match="config_or_os_egress_unavailable"):
        live.launch(str(tmp_path.resolve() / "out"))
    assert "BLOCKED" in capsys.readouterr().out


def test_launcher_serial_process_scope_stop_and_journal(tmp_path, monkeypatch, capsys):
    from contextlib import contextmanager
    from types import SimpleNamespace
    monkeypatch.setenv("CPA_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("HTTPS_PROXY", "unapproved")
    monkeypatch.setattr(live.sys, "platform", "darwin")
    monkeypatch.setattr(live.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    output = tmp_path.resolve() / "out"
    slots, _ = live.frozen()
    launched = []

    @contextmanager
    def connect(address, timeout):
        assert address == ("192.168.31.110", 8317)
        assert timeout == 60
        yield SimpleNamespace(fileno=lambda: 123)

    def execute(cmd, **kwargs):
        slot = slots[len(launched)]
        launched.append(slot["run_id"])
        assert '(deny network*)' in cmd[2]
        assert kwargs["pass_fds"] == (123,)
        assert "synthetic-private-key" not in repr(cmd)
        assert "HTTPS_PROXY" not in live.os.environ
        assert live.os.environ["CPA_API_KEY"] == "synthetic-private-key"
        assert 0 < kwargs["timeout"] <= 600
        private = live.pilot.PrivateOutput(output / slot["run_id"])
        private.write("row.json", json.dumps(slot | {"end_status": "STOP",
            "error_code": "synthetic_stop", "client_http_attempts": 1}))
        private.close()
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(live.socket, "create_connection", connect)
    monkeypatch.setattr(live.subprocess, "run", execute)
    assert live.launch(str(output)) == 1
    assert launched == [live.ORDER[0]]
    summary = json.loads((output / "summary.json").read_text())
    assert summary["client_http_attempts"] == 1
    assert summary["executed_slots"] == 1
    assert "synthetic-private-key" not in capsys.readouterr().out


def test_inherited_keepalive_loss_never_reconnects():
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"{}")
            self.close_connection = True

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    async def scenario(fd):
        target = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        async with httpx.AsyncClient(transport=live.probe.inherited_transport(fd, target),
                                     trust_env=False, timeout=2) as client:
            assert (await client.post(target, json={})).status_code == 200
            with pytest.raises(live.probe.Stop, match="reconnect_or_destination_denied"):
                await client.post(target, json={})
    try:
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as conn:
            # Duplicate ownership: inherited_transport owns the duplicated socket.
            asyncio.run(scenario(live.os.dup(conn.fileno())))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert len(seen) == 1


def test_sdk_usage_mismatch_and_deadline_stop():
    budget = live.LiveBudget(live.Scope(28, 1800))
    budget.begin("A", live.Scope(4, 600))
    budget.audit = [{"raw_usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                   "total_tokens": 15}}]
    with pytest.raises(live.pilot.Stop, match="sdk_usage_mismatch"):
        budget.receipt(AIMessage(content="synthetic", usage_metadata={"input_tokens": 11,
            "output_tokens": 5, "total_tokens": 16}), {}, [])
    budget = live.LiveBudget(live.Scope(28, 1800))
    budget.begin("A", live.Scope(4, 600))
    budget.deadline -= 601
    with pytest.raises(live.pilot.Stop, match="deadline"):
        budget.reserve()
    assert budget.attempts == 0
