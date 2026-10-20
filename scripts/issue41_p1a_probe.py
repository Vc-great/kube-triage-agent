"""Isolated P1-A CPA synthetic wire probes. No Graph, Reader execution or dotenv.

Default is offline preflight. Live requires an explicit exact endpoint, private
CPA_API_KEY injection and a macOS sandbox-exec child with no new network access.
The sole LAN HTTP exception is the exact endpoint explicitly approved by the user.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx
import issue41_b1r_pilot as pilot
from issue41_provider_contract import LOCKED

MODEL = "gpt-6-luna"
# User explicitly approved this sole plaintext LAN endpoint on 2026-10-20.
LAN_ENDPOINT = "http://192.168.31.110:8317/v1/chat/completions"
PROBE_LOCKED = LOCKED | {"httpcore": "1.0.9", "anyio": "4.15.1"}
ARGS = {"namespace": "kube-triage-demo", "name": "p1a-synthetic-pod"}
TEXT = "纯合成协议测试。请用中文回复：当前没有真实集群证据。"
TOOL_PROMPT = "纯合成协议测试。请调用 pods_get，namespace=kube-triage-demo，name=p1a-synthetic-pod。"
RECEIPT = json.dumps({"synthetic": True, "metadata": ARGS | {"uid": "p1a-fake-uid"},
                      "status": "Unknown", "evidence": "没有真实 Kubernetes 读取"}, ensure_ascii=False)


class Stop(RuntimeError):
    pass


def endpoint(value):
    """Canonical full route only; no credentials, query, escapes or DNS loopback alias."""
    try:
        u = urlsplit(value)
        port = u.port
        loop = u.hostname in {"127.0.0.1", "::1"}
        if (u.username or u.password or u.query or u.fragment
                or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*chat/completions", u.path)
                or not u.hostname or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        if loop:
            if u.scheme not in {"http", "https"} or port is None:
                raise ValueError
        elif value != LAN_ENDPOINT and (u.scheme != "https" or not re.fullmatch(
                r"[a-z0-9]+(?:[-.][a-z0-9]+)*\.[a-z]{2,}", u.hostname)):
            raise ValueError
        host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
        if value != f"{u.scheme}://{host}" + (f":{port}" if port else "") + u.path:
            raise ValueError
        return u
    except (ValueError, TypeError):
        raise Stop("endpoint_contract") from None


def schema():
    from kube_triage.mcp_client import ALLOWED_TOOLS, build_model_tool_schemas
    return next(t for t in build_model_tool_schemas(dict.fromkeys(ALLOWED_TOOLS))
                if t["function"]["name"] == "pods_get")


class Ledger:
    def __init__(self):
        self.started = time.monotonic()
        self.attempts = 0
        self.reason = None
        self.busy = False
        self.rows = []
        self.expected = None

    def stop(self, reason):
        self.reason = self.reason or reason
        raise Stop(self.reason)

    def check(self):
        if self.reason:
            raise Stop(self.reason)
        if time.monotonic() - self.started >= 600:
            self.stop("wall_clock")


def guard(inner, target, ledger):
    endpoint(target)

    class Guard(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            ledger.check()
            if ledger.busy:
                ledger.stop("parallel_disabled")
            ledger.busy = True
            row = None
            started = time.monotonic()
            try:
                body = json.loads(request.content)
                if (str(request.url) != target or request.method != "POST"
                        or body != ledger.expected):
                    ledger.stop("wire_request_contract")
                if ledger.attempts >= 24:
                    ledger.stop("attempt_limit")
                ledger.attempts += 1  # Reserve before any HTTP, never refund.
                row = {"attempt": ledger.attempts, "http_status": "UNKNOWN",
                       "raw_usage": "UNKNOWN", "sdk_usage": "UNKNOWN",
                       "request_model": MODEL, "request_sha256": hashlib.sha256(
                           request.content).hexdigest()}
                ledger.rows.append(row)
                async with asyncio.timeout(min(45, 600 - (started - ledger.started))):
                    response = await inner.handle_async_request(request)
                    await response.aread()
                ledger.check()
                row["http_status"] = response.status_code
                # Never persist arbitrary response/error bodies or headers.
                if response.status_code != 200:
                    ledger.stop("redirect" if response.is_redirect else "http_error")
                data = response.json()
                row["response_id_sha256"] = digest(data.get("id"))
                row["request_id_sha256"] = digest(response.headers.get("x-request-id"))
                row["model_echo"] = MODEL if data.get("model") == MODEL else "MISMATCH"
                row["model_echo_sha256"] = digest(data.get("model"))
                if data.get("model") != MODEL:
                    ledger.stop("model_echo_mismatch")
                row["raw_usage"] = usage(data.get("usage"))
                if row["raw_usage"] == "UNKNOWN":
                    row["usage_completeness"] = "UNKNOWN"
                else:
                    row["usage_completeness"] = "OBSERVED"
                choices = data.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    ledger.stop("choice_contract")
                finish = choices[0].get("finish_reason")
                row["finish_reason"] = finish if finish in {"stop", "tool_calls", "length"} else "UNKNOWN"
                if finish not in {"stop", "tool_calls"}:
                    ledger.stop("finish_contract")
                return response
            except BaseException:
                ledger.reason = ledger.reason or "transport_or_response_error"
                raise
            finally:
                if row is not None:
                    row["latency_ms"] = round((time.monotonic() - started) * 1000)
                ledger.busy = False

        async def aclose(self):
            await inner.aclose()

    return Guard()


def redact(value, key):
    """Private synthetic reply evidence; never persist headers or raw HTTP bodies."""
    if not isinstance(value, str):
        return "UNKNOWN"
    value = value.replace(key, "[REDACTED]") if key else value
    value = re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+", "[REDACTED]", value)
    return value[:8192]


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest() if value else "UNKNOWN"


def usage(value):
    if not isinstance(value, dict):
        return "UNKNOWN"
    result = {k: v for k, v in value.items() if k in {
        "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
        and type(v) is int and v >= 0}
    for outer, inner in (("prompt_tokens_details", "cached_tokens"),
                         ("completion_tokens_details", "reasoning_tokens"),
                         ("input_token_details", "cache_read"),
                         ("output_token_details", "reasoning")):
        v = value.get(outer)
        if isinstance(v, dict) and type(v.get(inner)) is int and v[inner] >= 0:
            result[outer] = {inner: v[inner]}
    return result or "UNKNOWN"


async def probes(target, key, inner, ledger):
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langchain_openai.chat_models.base import _convert_message_to_dict
    from langsmith import tracing_context

    if any(importlib.metadata.version(k) != v for k, v in PROBE_LOCKED.items()):
        ledger.stop("locked_sdk")
    async with httpx.AsyncClient(transport=guard(inner, target, ledger), timeout=45,
                                 trust_env=False, follow_redirects=False) as client:
        model = ChatOpenAI(model=MODEL, api_key=key,
            base_url=target.removesuffix("/chat/completions"), max_retries=0, timeout=45,
            use_responses_api=False, streaming=False, max_completion_tokens=1024,
            http_async_client=client)

        async def invoke(messages, tools=False):
            ledger.check()
            ledger.expected = {"model": MODEL, "stream": False, "max_completion_tokens": 1024,
                               "messages": [_convert_message_to_dict(m) for m in messages]}
            bound = model
            if tools:
                ledger.expected["tools"] = [schema()]
                bound = model.bind_tools([schema()])
            try:
                answer = await bound.ainvoke(messages, config={"callbacks": []})
                row = ledger.rows[-1]
                row["sdk_usage"] = usage(answer.usage_metadata)
                raw, sdk = row["raw_usage"], row["sdk_usage"]
                pairs = (("prompt_tokens", "input_tokens"),
                         ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens"))
                row["usage_comparison"] = "UNKNOWN"
                if (isinstance(raw, dict) and isinstance(sdk, dict)
                        and all(a in raw and b in sdk for a, b in pairs)):
                    row["usage_comparison"] = "MATCH" if all(raw[a] == sdk[b] for a, b in pairs) else "MISMATCH"
                    if row["usage_comparison"] == "MISMATCH":
                        ledger.stop("sdk_usage_mismatch")
                row["synthetic_reply_text"] = redact(answer.content, key)
                if isinstance(answer.content, str) and any(claim in answer.content for claim in
                        ("已健康", "已核验健康", "业务完全健康", "已修复", "根因已证实")):
                    ledger.stop("unsupported_claim")
                if answer.invalid_tool_calls:
                    ledger.stop("invalid_tool_calls")
                if row["finish_reason"] != ("tool_calls" if tools else "stop"):
                    ledger.stop("finish_message_mismatch")
                if tools:
                    if len(answer.tool_calls) != 1:
                        ledger.stop("tool_count")
                    call = answer.tool_calls[0]
                    from kube_triage.mcp_client import validate_call
                    validate_call(call["name"], call["args"])
                    if (call["name"] != "pods_get" or call["args"] != ARGS
                            or not isinstance(call["id"], str)
                            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", call["id"])):
                        ledger.stop("synthetic_tool_contract")
                    ledger.rows[-1]["tool_id_sha256"] = digest(call["id"])
                    ledger.rows[-1]["tool_name"] = "pods_get"
                    ledger.rows[-1]["synthetic_tool_args"] = dict(ARGS)
                elif answer.tool_calls or not isinstance(answer.content, str) or not answer.content.strip():
                    ledger.stop("text_contract")
                ledger.rows[-1]["content_sha256"] = digest(answer.content)
                return answer
            except BaseException:
                ledger.reason = ledger.reason or "sdk_or_message_error"
                raise

        with tracing_context(enabled=False):
            await invoke([HumanMessage(TEXT)])
            messages = [HumanMessage(TOOL_PROMPT)]
            answer = await invoke(messages, tools=True)
            call = answer.tool_calls[0]
            await invoke(messages + [answer, ToolMessage(RECEIPT, tool_call_id=call["id"],
                                                        name="pods_get")])


@contextmanager
def isolated_environment(key=None):
    from unittest.mock import patch
    env = {"PATH": os.defpath, "TRIAGE_ENV": "test", "OTEL_SDK_DISABLED": "true",
           "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    if key:
        env["CPA_API_KEY"] = key
    with patch.dict(os.environ, env, clear=True):
        yield


def summary(ledger):
    protocol = "PASS" if not ledger.reason else ("FAIL" if ledger.attempts else "BLOCKED")
    return {"stage": "P1-A", "status": "UNKNOWN" if protocol == "PASS" else protocol,
            "protocol_status": protocol, "semantic_status": "UNKNOWN",
            "semantic_review": "NOT RUN",
            "stop_reason": ledger.reason, "client_http_attempts": ledger.attempts,
            "rows": ledger.rows, "upstream_retries": "UNKNOWN", "billing": "UNKNOWN",
            "B8": "NOT RUN", "P1-B": "NOT AUTHORIZED", "kubernetes_requests": 0}


def inherited_transport(fd, target):
    """Use exactly one preconnected socket; no DNS, reconnect or second destination.

    httpx's private pool seam is covered against the frozen httpcore/anyio versions.
    The child OS policy forbids connect(), including when keep-alive is lost.
    """
    import httpcore
    from anyio.abc import SocketStream
    from httpcore._backends.anyio import AnyIOStream

    u = endpoint(target)
    sock = socket.socket(fileno=fd)
    peer = sock.getpeername()
    if peer[:2] != (u.hostname, u.port):
        sock.close()
        raise Stop("inherited_peer_mismatch")

    class Backend(httpcore.AsyncNetworkBackend):
        used = False

        async def connect_tcp(self, host, port, **kwargs):
            if self.used or host != u.hostname or port != u.port:
                raise Stop("reconnect_or_destination_denied")
            self.used = True
            return AnyIOStream(await SocketStream.from_socket(sock))

        async def connect_unix_socket(self, path, **kwargs):
            raise Stop("unix_socket_denied")

    transport = httpx.AsyncHTTPTransport(verify=True, retries=0, trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(network_backend=Backend(), retries=0,
        max_connections=1, max_keepalive_connections=1, keepalive_expiry=600)
    return transport


def child(target, fd, output, started):
    """The only network capability is the inherited socket to the approved peer."""
    key = os.environ.get("CPA_API_KEY")
    ledger = Ledger()
    ledger.started = started
    private = pilot.PrivateOutput(output)
    try:
        with isolated_environment():
            asyncio.run(probes(target, key, inherited_transport(fd, target), ledger))
    except BaseException:  # noqa: BLE001 - never expose provider exceptions/secrets
        ledger.reason = ledger.reason or "probe_error"
    finally:
        private.write("summary.json", json.dumps(summary(ledger), ensure_ascii=False, indent=2))
        private.close()
    public = {k: v for k, v in summary(ledger).items() if k != "rows"}
    print(json.dumps(public, ensure_ascii=False))
    return 0 if not ledger.reason else 1


def launch(target, output):
    started = time.monotonic()
    u = endpoint(target)
    key = os.environ.get("CPA_API_KEY")
    executable = shutil.which("sandbox-exec")
    if not key or not executable or sys.platform != "darwin":
        raise Stop("config_or_os_egress_unavailable")
    if u.hostname not in {"127.0.0.1", "::1"} and target != LAN_ENDPOINT:
        raise Stop("remote_os_egress_unavailable")
    # One numeric destination is connected before sandbox activation. This sends
    # no HTTP/Key. The child inherits only this network socket and cannot reconnect.
    with socket.create_connection((u.hostname, u.port), timeout=45) as connected:
        fd = connected.fileno()
        code = (f"import sys; sys.path.insert(0, {str(pilot.prep.ROOT / 'scripts')!r}); "
                f"import issue41_p1a_probe as p; "
                f"sys.exit(p.child({target!r}, {fd!r}, {output!r}, {started!r}))")
        with isolated_environment(key):
            return subprocess.run([executable, "-p", '(version 1)(allow default)(deny network*)',
                sys.executable, "-I", "-c", code], pass_fds=(fd,), check=False,
                timeout=max(1, 600 - (time.monotonic() - started))).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-p1a", action="store_true")
    parser.add_argument("--endpoint", help="explicit approved full Chat Completions URL; no secrets")
    parser.add_argument("--output", help="new absolute private directory")
    args = parser.parse_args()
    try:
        if not args.live_p1a or not args.endpoint or not args.output:
            raise Stop("explicit_live_config_required")
        return launch(args.endpoint, args.output)
    except BaseException:  # noqa: BLE001 - sanitized failure only
        print('{"stage":"P1-A","status":"BLOCKED","reason":"preflight_or_launch",'
              '"upstream_retries":"UNKNOWN","billing":"UNKNOWN","B8":"NOT RUN"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
