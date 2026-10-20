"""P1-A negative tests use only synthetic HTTP and OS denied network."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import issue41_p1a_probe as p

sys.path.pop(0)

TARGET = "https://cpa.invalid/v1/chat/completions"


def response(step, **overrides):
    msg = {"role": "assistant", "content": "纯合成：当前状态未核验。"}
    if step == 2:
        msg["tool_calls"] = [{"id": "synthetic-call", "type": "function", "function": {
            "name": "pods_get", "arguments": json.dumps(p.ARGS)}}]
    return httpx.Response(200, json={"id": "synthetic-reply", "object": "chat.completion",
        "created": 0, "model": p.MODEL, "choices": [{"index": 0, "message": msg,
        "finish_reason": "tool_calls" if step == 2 else "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}} | overrides)


def run(handler):
    ledger = p.Ledger()
    with p.pilot.offline():
        try:
            asyncio.run(p.probes(TARGET, "synthetic-key", httpx.MockTransport(handler), ledger))
        except Exception:  # noqa: BLE001 - assert sticky ledger below
            assert ledger.reason
    return ledger


def test_three_steps_paired_and_p0_unchanged():
    seen = []
    def handler(req):
        seen.append(json.loads(req.content))
        assert len(seen) <= 3
        assert seen[-1]["model"] == p.MODEL
        assert "responses" not in str(req.url)
        assert seen[-1]["max_completion_tokens"] == 1024
        if len(seen) == 3:
            assert seen[-1]["messages"][-1]["tool_call_id"] == "synthetic-call"
            assert seen[-1]["messages"][-1]["content"] == p.RECEIPT
        return response(len(seen))
    ledger = run(handler)
    assert ledger.reason is None, ledger.reason
    assert ledger.attempts == len(seen) == 3
    assert all(r["sdk_usage"]["total_tokens"] == 15 for r in ledger.rows)
    from issue41_provider_contract import synthetic_profile
    assert synthetic_profile().live_gate()["status"] == "BLOCKED"


@pytest.mark.parametrize("target", ["http://evil.test/v1/chat/completions",
    "http://localhost:8080/v1/chat/completions", "http://0.0.0.0:8/chat/completions",
    "https://user:secret@evil.test/v1/chat/completions", TARGET + "?key=secret",
    TARGET + "#x", "https://cpa.invalid/v1/%2e/chat/completions",
    "https://cpa.invalid:0/chat/completions", "https://127.0.0.2/chat/completions"])
def test_endpoint_reject(target):
    with pytest.raises(p.Stop):
        p.endpoint(target)


@pytest.mark.parametrize("target", [TARGET, "http://127.0.0.1:8080/v1/chat/completions",
                                    "http://[::1]:8080/v1/chat/completions"])
def test_endpoint_accept(target):
    p.endpoint(target)


@pytest.mark.parametrize("status", [301, 302, 307, 400, 403, 422, 429, 500, 503])
def test_http_failure_no_retry_or_next_step(status):
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(status, headers={"location": "https://other.invalid/"})
    ledger = run(handler)
    assert ledger.reason in {"http_error", "redirect"}
    assert ledger.attempts == len(seen) == 1
    assert ledger.rows[0]["http_status"] == status


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, RuntimeError])
def test_exception_stop(failure):
    def handler(req):
        raise failure("secret-error-body-never-persist")
    ledger = run(handler)
    assert ledger.reason
    assert ledger.attempts == 1
    assert "secret-error" not in json.dumps(p.summary(ledger))


@pytest.mark.parametrize("mutation,reason", [
    ({"model": "different-private-alias"}, "model_echo_mismatch"),
    ({"choices": []}, "choice_contract"),
    ({"choices": [{"finish_reason": "length"}]}, "finish_contract"),
])
def test_response_failure(mutation, reason):
    ledger = run(lambda req: response(1, **mutation))
    assert ledger.reason == reason
    assert ledger.attempts == 1
    if reason == "model_echo_mismatch":
        assert ledger.rows[0]["model_echo_redacted"] == "different-private-alias"


def test_usage_missing_remains_unknown():
    n = 0
    def handler(req):
        nonlocal n
        n += 1
        return response(n, usage=None)
    ledger = run(handler)
    assert ledger.reason is None
    assert all(r["raw_usage"] == r["sdk_usage"] == "UNKNOWN" for r in ledger.rows)


@pytest.mark.parametrize("name,args,id_", [
    ("resources_scale", p.ARGS, "id"),
    ("pods_get", p.ARGS | {"namespace": "other"}, "id"),
    ("pods_get", p.ARGS | {"name": "real-pod"}, "id"),
    ("pods_get", p.ARGS, ""),
])
def test_unapproved_tool_stop_before_receipt(name, args, id_):
    n = 0
    def handler(req):
        nonlocal n
        n += 1
        data = response(n).json()
        if n == 2:
            call = data["choices"][0]["message"]["tool_calls"][0]
            call["id"] = id_
            call["function"] = {"name": name, "arguments": json.dumps(args)}
        return httpx.Response(200, json=data)
    ledger = run(handler)
    assert ledger.reason
    assert ledger.attempts == n == 2


def test_presend_limit_parallel_deadline_sticky():
    async def scenario(kind):
        ledger = p.Ledger()
        ledger.expected = {}
        seen = []
        def handler(req):
            seen.append(req)
            return response(1)
        transport = p.guard(httpx.MockTransport(handler), TARGET, ledger)
        if kind == "limit":
            ledger.attempts = 24
        elif kind == "parallel":
            ledger.busy = True
        else:
            ledger.started -= 601
        for _ in range(2):
            with pytest.raises(p.Stop):
                await transport.handle_async_request(httpx.Request("POST", TARGET, json={}))
        assert not seen
    for kind in ["limit", "parallel", "deadline"]:
        asyncio.run(scenario(kind))


@pytest.mark.parametrize("url,body", [("https://other.invalid/v1/chat/completions", {}),
                                       (TARGET, {"messages": ["real-data"]})])
def test_wire_denied_before_count(url, body):
    ledger = p.Ledger()
    ledger.expected = {}
    async def scenario():
        async with httpx.AsyncClient(transport=p.guard(httpx.MockTransport(
                lambda req: pytest.fail("must not send")), TARGET, ledger)) as client:
            with pytest.raises(p.Stop):
                await client.post(url, json=body)
    asyncio.run(scenario())
    assert ledger.attempts == 0


def test_default_cli_no_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe"])
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS"))
    assert p.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_launch_missing_injection_no_dns(monkeypatch):
    monkeypatch.delenv("CPA_API_KEY", raising=False)
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS"))
    with pytest.raises(p.Stop):
        p.launch(TARGET, "/unused")


@pytest.mark.parametrize("step", [1, 2, 3])
def test_mixed_content_unsupported_claim_stops(step):
    n = 0
    def handler(req):
        nonlocal n
        n += 1
        data = response(n).json()
        if n == step:
            data["choices"][0]["message"]["content"] = "已核验健康，已修复"
        return httpx.Response(200, json=data)
    ledger = run(handler)
    assert ledger.reason == "unsupported_claim"
    assert ledger.attempts == step


def test_corrupt_json_sticky():
    ledger = run(lambda req: httpx.Response(200, text="not-json-secret"))
    assert ledger.attempts == 1
    assert ledger.reason == "transport_or_response_error"
    assert "not-json-secret" not in json.dumps(p.summary(ledger))


def test_http_timeout_is_sticky(monkeypatch):
    original = asyncio.timeout
    monkeypatch.setattr(p.asyncio, "timeout", lambda seconds: original(0.001))
    async def handler(req):
        await asyncio.sleep(0.1)
        return response(1)
    ledger = run(handler)
    assert ledger.attempts == 1
    assert ledger.reason == "transport_or_response_error"


def test_launch_environment_and_policy(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("CPA_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.invalid")
    monkeypatch.setenv("LANGSMITH_API_KEY", "synthetic-unapproved")
    monkeypatch.setattr(p.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(p.sys, "platform", "darwin")
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("1.1.1.1", 443))])
    def execute(cmd, **kw):
        assert cmd[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert '(deny network*)' in cmd[2]
        assert 'allow network-outbound' not in cmd[2]
        assert kw['pass_fds'] == (123,)
        assert "synthetic-private-key" not in repr(cmd)
        assert p.os.environ["CPA_API_KEY"] == "synthetic-private-key"
        assert "HTTPS_PROXY" not in p.os.environ
        assert "LANGSMITH_API_KEY" not in p.os.environ
        assert 0 < kw["timeout"] <= 600
        return SimpleNamespace(returncode=0)
    from contextlib import contextmanager
    @contextmanager
    def connect(address, timeout):
        assert address == ("127.0.0.1", 8080)
        assert timeout == 45
        yield SimpleNamespace(fileno=lambda: 123)
    monkeypatch.setattr(p.socket, "create_connection", connect)
    monkeypatch.setattr(p.subprocess, "run", execute)
    assert p.launch("http://127.0.0.1:8080/v1/chat/completions",
                    "/private/tmp/synthetic-unused") == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS OS egress policy verification")
def test_os_egress_inherited_connection_and_all_new_connections_denied():
    import socket
    import subprocess
    with socket.socket() as allowed, socket.socket() as denied:
        allowed.bind(("127.0.0.1", 0))
        denied.bind(("127.0.0.1", 0))
        allowed.listen()
        denied.listen()
        port = allowed.getsockname()[1]
        other = denied.getsockname()[1]
        code = f'''
import socket,sys
s = socket.socket(fileno=int(sys.argv[1])); s.settimeout(1)
s.sendall(b"synthetic"); s.close()
for port in ({port}, {other}):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1)
    except PermissionError:
        continue
    raise RuntimeError("egress escaped")
print("OS_EGRESS_PASS")
'''
        with socket.create_connection(("127.0.0.1", port), timeout=2) as approved:
            result = subprocess.run(["/usr/bin/sandbox-exec", "-p",
                '(version 1)(allow default)(deny network*)', sys.executable, "-I", "-c", code,
                str(approved.fileno())], pass_fds=(approved.fileno(),), check=False,
                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OS_EGRESS_PASS"
        allowed.settimeout(2)
        conn, _ = allowed.accept()
        with conn:
            conn.settimeout(2)
            assert conn.recv(20) == b"synthetic"


def test_remote_os_gate_no_dns(monkeypatch):
    monkeypatch.setenv("CPA_API_KEY", "synthetic-only")
    monkeypatch.setattr(p.sys, "platform", "darwin")
    monkeypatch.setattr(p.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS"))
    with pytest.raises(p.Stop, match="remote_os_egress_unavailable"):
        p.launch(TARGET, "/unused")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS isolated child smoke test")
@pytest.mark.parametrize("fail_last", [False, True])
def test_loopback_synthetic_child_private_evidence(tmp_path, monkeypatch, capfd, fail_last):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    requests = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = response(len(requests)).content
            self.send_response(500 if fail_last and len(requests) == 3 else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("CPA_API_KEY", "synthetic-child-key")
    output = tmp_path.resolve() / "probe"
    try:
        result = p.launch(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", str(output))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result == (1 if fail_last else 0)
    assert len(requests) == 3
    public = json.loads(capfd.readouterr().out)
    assert "rows" not in public
    assert "synthetic_reply_text" not in json.dumps(public)
    assert "纯合成：当前状态未核验。" not in json.dumps(public, ensure_ascii=False)
    saved = (output / "summary.json").read_text()
    assert json.loads(saved)["status"] == ("FAIL" if fail_last else "UNKNOWN")
    assert json.loads(saved)["protocol_status"] == ("FAIL" if fail_last else "PASS")
    assert json.loads(saved)["rows"][0]["synthetic_reply_text"] == "纯合成：当前状态未核验。"
    assert "synthetic-child-key" not in saved
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / "summary.json").stat().st_mode & 0o777 == 0o600


def test_redaction_usage_whitelist():
    assert p.redact("key-value bearer abcdef sk-secret", "key-value") == (
        "[REDACTED] [REDACTED] [REDACTED]")
    assert p.usage({"private_field": "secret", "total_tokens": 1}) == {"total_tokens": 1}
    assert p.usage({"prompt_tokens": -1, "completion_tokens": True}) == "UNKNOWN"


def test_tool_finish_reason_must_match():
    n = 0
    def handler(req):
        nonlocal n
        n += 1
        data = response(n).json()
        if n == 2:
            data["choices"][0]["finish_reason"] = "stop"
        return httpx.Response(200, json=data)
    ledger = run(handler)
    assert ledger.attempts == 2
    assert ledger.reason == "finish_message_mismatch"


def test_synonym_claim_cannot_pass_semantic_gate():
    n = 0
    def handler(req):
        nonlocal n
        n += 1
        data = response(n).json()
        if n == 3:
            data["choices"][0]["message"]["content"] = "该 Pod 运行正常，故障已经解决"
        return httpx.Response(200, json=data)
    ledger = run(handler)
    assert ledger.reason is None
    result = p.summary(ledger)
    assert result["protocol_status"] == "PASS"
    assert result["status"] == result["semantic_status"] == "UNKNOWN"
    assert result["semantic_review"] == "NOT RUN"


def test_lan_exception_is_exact():
    p.endpoint(p.LAN_ENDPOINT)
    for target in [p.LAN_ENDPOINT.replace(".110", ".111"),
                   p.LAN_ENDPOINT.replace(":8317", ":8318"),
                   p.LAN_ENDPOINT.replace("/v1/", "/v2/"),
                   p.LAN_ENDPOINT + "?key=no", p.LAN_ENDPOINT + "/"]:
        with pytest.raises(p.Stop):
            p.endpoint(target)


def test_inherited_backend_no_reconnect_or_other_route(monkeypatch):
    from types import SimpleNamespace

    from anyio.abc import SocketStream

    async def scenario():
        with monkeypatch.context() as patch:
            fake = SimpleNamespace(getpeername=lambda: ("127.0.0.1", 8080), close=lambda: None)
            patch.setattr(p.socket, "socket", lambda **kw: fake)
            async def wrap(sock):
                assert sock is fake
                return object()
            patch.setattr(SocketStream, "from_socket", wrap)
            transport = p.inherited_transport(123, "http://127.0.0.1:8080/v1/chat/completions")
            backend = transport._pool._network_backend
            with pytest.raises(p.Stop, match="reconnect_or_destination_denied"):
                await backend.connect_tcp("127.0.0.2", 8080)
            await backend.connect_tcp("127.0.0.1", 8080)
            with pytest.raises(p.Stop, match="reconnect_or_destination_denied"):
                await backend.connect_tcp("127.0.0.1", 8080)
            with pytest.raises(p.Stop, match="unix_socket_denied"):
                await backend.connect_unix_socket("/fake")
            fake.getpeername = lambda: ("127.0.0.2", 8080)
            with pytest.raises(p.Stop, match="inherited_peer_mismatch"):
                p.inherited_transport(123, "http://127.0.0.1:8080/v1/chat/completions")
    asyncio.run(scenario())


def test_secret_echo_in_model_is_redacted():
    ledger = run(lambda req: response(1, model="synthetic-key"))
    assert ledger.reason == "model_echo_mismatch"
    assert "synthetic-key" not in json.dumps(p.summary(ledger))
    assert ledger.rows[0]["model_echo_redacted"] == "[REDACTED]"


def test_preconnect_failure_private_zero_http_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("CPA_API_KEY", "synthetic-key")
    monkeypatch.setattr(p.sys, "platform", "darwin")
    monkeypatch.setattr(p.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    def fail(*args, **kwargs):
        raise ConnectionRefusedError(61, "synthetic-secret-must-not-be-recorded")
    monkeypatch.setattr(p.socket, "create_connection", fail)
    output = tmp_path.resolve() / "failure"
    with pytest.raises(p.Stop, match="tcp_preconnect_error"):
        p.launch("http://127.0.0.1:8080/v1/chat/completions", str(output))
    raw = (output / "summary.json").read_text()
    audit = json.loads(raw)
    assert audit["client_http_attempts"] == 0
    assert audit["protocol_status"] == "NOT RUN"
    assert audit["error_class"] == "ConnectionRefusedError"
    assert audit["errno"] == 61
    assert "synthetic-secret" not in raw
