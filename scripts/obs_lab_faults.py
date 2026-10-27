"""Test-only Phase B outcomes and bounded, fixed-origin model fault injection."""

import threading
import urllib.error
import urllib.request
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from obs_lab_verify import decoded, signature

FAULTS = {"S04": "timeout", "S05": "permission_denied", "S06": "business_error"}


def outcome(payload):
    if not isinstance(payload, dict):
        return "unknown"
    if payload.get("ok") is False:
        return {"timeout": "timeout", "forbidden": "permission_denied",
                "policy": "policy_rejected", "budget": "budget_skipped"}.get(
                    payload.get("error_type"), "unknown")
    inner = decoded(payload.get("result"))
    if isinstance(inner, dict) and inner.get("ok") is False:
        return "business_error"
    return "success" if payload.get("ok") is True else "unknown"


def inspect_faults(messages, scenario):
    calls = [call for msg in messages if msg.get("type", msg.get("role")) in {"ai", "assistant"}
             for call in msg.get("tool_calls", [])]
    results = {msg.get("tool_call_id"): decoded(msg.get("content")) for msg in messages
               if msg.get("type", msg.get("role")) == "tool"}
    records = [{"tool_call_id": c.get("id"), "name": c.get("name"),
                "signature": signature(c.get("name"), c.get("args")),
                "outcome": outcome(results.get(c.get("id"))),
                "wrapper_success": (results.get(c.get("id")) or {}).get("ok")}
               for c in calls]
    decision = 0
    by_id = {r["tool_call_id"]: r for r in records}
    for message in messages:
        if message.get("type", message.get("role")) in {"ai", "assistant"}:
            decision += 1
            for call in message.get("tool_calls", []):
                by_id[call["id"]]["model_decision"] = decision
    counts = Counter(r["signature"] for r in records)
    duplicates = sum(n - 1 for n in counts.values() if n > 1)
    expected = FAULTS.get(scenario)

    def expected_fault(record):
        tool = "pods_get" if scenario == "S05" else "pods_log"
        return (expected is not None and record["outcome"] == expected
                and record["name"] == tool and record["signature"] is not None
                and decoded(record["signature"][1]).get("name") == "sample-a")

    return {"records": records, "expected_outcome": expected,
            "fault_observed": any(expected_fault(r) for r in records) if expected else None,
            "unexpected_outcomes": [r["outcome"] for r in records
                                    if r["outcome"] != "success" and not expected_fault(r)],
            "duplicate_count": duplicates,
            "duplicate_event": "TRIGGERED" if duplicates else "NOT_TRIGGERED"}



def retry_recovered(attempts, decisions):
    return bool(attempts and attempts[0]["status"] == 429 and not attempts[0]["forwarded"]
                and len(attempts) == decisions + 1 and len(attempts) <= 8
                and [a["attempt"] for a in attempts] == list(range(1, len(attempts) + 1))
                and len(attempts) > 1
                and all(a["forwarded"] and a["status"] == 200 for a in attempts[1:]))

def observed_reader(original):
    async def call(name, arguments, thread_id=None):
        from langchain_core.runnables import RunnableLambda

        from kube_triage.app_storage import _reader_context

        context = _reader_context.get() or {}
        payload = None

        async def invoke(_input):
            nonlocal payload
            payload = await original(name, arguments, thread_id)
            return {"tool_outcome": outcome(payload), "wrapper_success": payload.get("ok"),
                    "tool_name": name, "tool_call_id": context.get("tool_call_id")}

        # OpenInference propagates LangChain callback parents, not OTel current spans.
        # The real Tool runs inside this Runnable; only the summary is its output.
        await RunnableLambda(invoke, name="reader_outcome").ainvoke({
            "tool_name": name, "tool_call_id": context.get("tool_call_id")})
        return payload
    return call


@contextmanager
def model_429(values, validate_provider, write_stats):
    """One synthetic 429, then real fixed-origin forwarding, at most 8 HTTP attempts."""
    validate_provider(values["LLM_BASE_URL"])
    target = values["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    records = []
    lock = threading.Lock()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256 * 1024:
                self.send_error(413)
                return
            body = self.rfile.read(length)
            with lock:
                number = len(records) + 1
                record = {"attempt": number, "forwarded": False, "status": None}
                records.append(record)
            if number == 1:
                status, data = 429, b'{"error":{"message":"Synthetic lab rate limit","type":"rate_limit_error","code":"rate_limit_exceeded"}}'
            elif number > 8:
                status, data = 503, b'{"error":{"message":"Lab HTTP budget exhausted"}}'
            else:
                record["forwarded"] = True
                request = urllib.request.Request(target, data=body, headers={
                    "Authorization": "Bearer " + values["LLM_API_KEY"],
                    "Content-Type": "application/json"})
                try:
                    with opener.open(request, timeout=30) as response:
                        status, data = response.status, response.read(2 * 1024 * 1024 + 1)
                except urllib.error.HTTPError as error:
                    status = error.code
                    data = b'{"error":{"message":"Provider request failed"}}'
                except (OSError, TimeoutError):
                    status, data = 502, b'{"error":{"message":"Provider transport failed"}}'
                if len(data) > 2 * 1024 * 1024:
                    status, data = 502, b'{"error":{"message":"Provider response too large"}}'
            record["status"] = status
            write_stats(records)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            if status == 429:
                self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        write_stats(records)
