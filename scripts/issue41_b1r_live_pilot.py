"""P1-B only: four frozen Graph runs, CPA + synthetic Reader, no automatic retry.

Live is explicit. Each slot gets a fresh OS-restricted process and one inherited
TCP connection. Losing keep-alive stops the batch; no reconnect permission exists.
P0/P1-A and the offline readiness CLI retain their original contracts.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import issue41_b1r_pilot as pilot
import issue41_p1a_probe as probe

TARGET = probe.LAN_ENDPOINT
MODEL = probe.MODEL
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
ORDER = ("R05-uid-injection-rep1-B", "R05-uid-injection-rep1-A",
         "R01-crashloop-rep1-B", "R01-crashloop-rep1-A")
LOCKED = probe.PROBE_LOCKED | {"deepagents": "0.7.28"}


@dataclass(frozen=True)
class Scope:
    attempts: int
    seconds: float
    # Legacy execute() emits these fields; annotate() removes synthetic fields.
    tokens: int = 0
    cost: int = 0


def frozen():
    manifest, cases = pilot.prep._load_frozen()
    slots = pilot.pilot_slots(manifest)
    if tuple(s["run_id"] for s in slots) != ORDER:
        raise pilot.Stop("frozen_order")
    if any(importlib.metadata.version(k) != v for k, v in LOCKED.items()):
        raise pilot.Stop("locked_sdk")
    return slots, cases


class LiveBudget(pilot.Budget):
    # No synthetic tokenizer/price is claimed as a real input-token bound.
    INPUT = math.inf
    OUTPUT = 1024

    def __init__(self, total, output=None):
        super().__init__(total)
        self.output = output
        self.in_flight = False

    def reserve(self):
        self.check()
        if (self.attempts >= self.total.attempts
                or self.run_attempts >= self.run_limits.attempts):
            self.stop("request_budget")
        self.attempts += 1
        self.run_attempts += 1
        # Durable reservation precedes delegation, even for failed/time-out HTTP.
        if self.output:
            self.output.write(f"attempt-{self.attempts:02d}.json", json.dumps({
                "attempt": self.attempts, "state": "reserved_before_send"}))

    def receipt(self, message, case, messages):
        raw = self.audit[-1]["raw_usage"]
        sdk = message.usage_metadata or {}
        if any(sdk.get(s) != raw.get(r) for s, r in (
            ("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"))):
            self.stop("sdk_usage_mismatch")
        for outer, field, sdk_outer, sdk_field in (
            ("prompt_tokens_details", "cached_tokens", "input_token_details", "cache_read"),
            ("completion_tokens_details", "reasoning_tokens", "output_token_details", "reasoning"),
        ):
            if field in raw.get(outer, {}) and sdk.get(sdk_outer, {}).get(sdk_field) != raw[outer][field]:
                self.stop("sdk_usage_details_mismatch")
        self.audit[-1]["sdk_usage"] = sdk
        self.audit[-1]["usage_match"] = True
        super().receipt(message, case, messages)


class LiveAdapter:
    def __init__(self, key, *, live=False):
        self.key = key
        self.live = live

    def make_model(self, client, budget, case):
        from langchain_openai import ChatOpenAI

        class AuditedModel(ChatOpenAI):
            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                budget.decision()
                try:
                    result = await super()._agenerate(messages, stop, run_manager, **kwargs)
                    if len(result.generations) != 1:
                        budget.stop("generation_count")
                    budget.receipt(result.generations[0].message, case, messages)
                    return result
                except BaseException:
                    budget.reason = budget.reason or "model_error"
                    raise

        return AuditedModel(model=MODEL, base_url=TARGET.removesuffix("/chat/completions"),
            api_key=self.key, http_async_client=client, timeout=60, max_retries=0,
            max_completion_tokens=1024, use_responses_api=False, streaming=False,
            disable_streaming=True, callbacks=[], cache=False)

    def guarded_transport(self, inner, budget):
        if not self.live and type(inner) is not httpx.MockTransport:
            budget.stop("offline_mock_only")
        key = self.key

        class Guard(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                budget.check()
                if budget.in_flight:
                    budget.stop("parallel_http_disabled")
                budget.in_flight = True
                audit = None
                started = time.monotonic()
                try:
                    if len(request.content) > MAX_REQUEST_BYTES:
                        budget.stop("request_body_limit")
                    body = json.loads(request.content)
                    tools = body.get("tools", [])
                    allowed = pilot.prep.READERS | ({"write_todos"} if budget.arm == "B" else set())
                    if (str(request.url) != TARGET or request.method != "POST"
                        or request.headers.get("authorization") != f"Bearer {key}"
                        or request.headers.get("host") != "192.168.31.110:8317"
                        or body.get("model") != MODEL or body.get("stream") is not False
                        or body.get("n", 1) != 1 or body.get("max_completion_tokens") != 1024
                        or set(body) - {"model", "messages", "stream", "max_completion_tokens",
                                        "tools", "tool_choice", "parallel_tool_calls", "n"}
                        or not isinstance(body.get("messages"), list)
                        or not isinstance(tools, list) or len(tools) != len(allowed)
                        or {t.get("function", {}).get("name") for t in tools} != allowed
                        or any(t.get("type") != "function" for t in tools)):
                        budget.stop("request_contract")
                    budget.reserve()
                    audit = {"attempt": budget.attempts, "http_status": "UNKNOWN",
                        "raw_usage": {}, "sdk_usage": "UNKNOWN", "usage_match": False,
                        "request_sha256": hashlib.sha256(request.content).hexdigest()}
                    budget.audit.append(audit)
                    # Reject compression before httpx can decode a potentially
                    # unbounded expansion. The approved wire contract is identity.
                    request.headers["accept-encoding"] = "identity"
                    async with asyncio.timeout(min(60, budget.deadline - time.monotonic(),
                            budget.total.seconds - (time.monotonic() - budget.started))):
                        response = await inner.handle_async_request(request)
                        try:
                            if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                                budget.stop("response_encoding")
                            chunks = []
                            size = 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > MAX_RESPONSE_BYTES:
                                    budget.stop("response_body_limit")
                                chunks.append(chunk)
                            data_bytes = b"".join(chunks)
                        finally:
                            await response.aclose()
                    budget.check()
                    audit["http_status"] = response.status_code
                    if response.status_code != 200:
                        budget.stop("redirect_disabled" if response.is_redirect else "http_failure")
                    data = json.loads(data_bytes)
                    audit.update(response_id_sha256=probe.digest(data.get("id")),
                                 request_id_sha256=probe.digest(response.headers.get("x-request-id")))
                    if data.get("model") != MODEL:
                        budget.stop("model_echo")
                    budget.model_echoed = MODEL
                    raw = probe.usage(data.get("usage"))
                    if not isinstance(raw, dict) or any(type(raw.get(k)) is not int for k in
                            ("prompt_tokens", "completion_tokens", "total_tokens")):
                        budget.stop("usage_unknown")
                    audit["raw_usage"] = raw
                    if (raw["prompt_tokens"] + raw["completion_tokens"] != raw["total_tokens"]
                            or raw["completion_tokens"] > 1024):
                        budget.stop("usage_invalid")
                    for outer, name, maximum in (
                        ("prompt_tokens_details", "cached_tokens", raw["prompt_tokens"]),
                        ("completion_tokens_details", "reasoning_tokens", raw["completion_tokens"]),
                    ):
                        details = data["usage"].get(outer)
                        if details is not None and (not isinstance(details, dict)
                                or type(details.get(name)) is not int
                                or not 0 <= details[name] <= maximum):
                            budget.stop("usage_details_unknown")
                    choices = data.get("choices")
                    if not isinstance(choices, list) or len(choices) != 1:
                        budget.stop("generation_count")
                    choice = choices[0]
                    finish = choice.get("finish_reason")
                    audit["finish_reason"] = finish if finish in {"stop", "tool_calls", "length"} else "UNKNOWN"
                    if finish not in {"stop", "tool_calls"}:
                        budget.stop("finish_contract")
                    if bool(choice.get("message", {}).get("tool_calls")) != (finish == "tool_calls"):
                        budget.stop("finish_message_mismatch")
                    return httpx.Response(200, content=data_bytes, headers={
                        "content-type": "application/json"}, request=request)
                except BaseException:
                    budget.reason = budget.reason or "transport_or_response_error"
                    raise
                finally:
                    if audit is not None:
                        audit["latency_ms"] = round((time.monotonic() - started) * 1000)
                    budget.in_flight = False

            async def aclose(self):
                await inner.aclose()

        return Guard()

    def annotate(self, row):
        for name in ("simulated_http_attempts", "reserved_tokens", "reserved_synthetic_cost",
                     "currency", "run_limits"):
            row.pop(name, None)
        row.update(stage="P1-B", evidence_level=("RealCPA+SDK+SyntheticMockReader" if self.live
            else "OfflineSDK+MockTransport+SyntheticMockReader"), model_requested=MODEL,
            provider_request_attempts=len(row["request_audit"]) if self.live else 0,
            client_http_attempts=len(row["request_audit"]), endpoint_class="exact-approved-CPA-LAN",
            usage_source="real_wire+SDK" if self.live else "synthetic_wire+SDK",
            actual_cost="UNKNOWN", upstream_retries="UNKNOWN", input_token_bound="UNKNOWN",
            provider_config_fingerprint=probe.digest("P1-B/exact-CPA/chat/retry=0/out=1024"))
        row["todo_updates"] = [call["args"]["todos"] for reply in row["raw_replies"]
            for call in reply.get("tool_calls", []) if call["name"] == "write_todos"]
        row.setdefault("todo_calls_attempted", len(row["todo_updates"]))
        row.setdefault("todo_calls_accepted", "UNKNOWN")
        row.setdefault("tool_call_id_paired", "UNKNOWN")


def redact_tree(data, key):
    if isinstance(data, str):
        return data.replace(key, "[REDACTED]") if key else data
    if isinstance(data, list):
        return [redact_tree(v, key) for v in data]
    if isinstance(data, dict):
        return {redact_tree(k, key): redact_tree(v, key) for k, v in data.items()}
    return data


async def run_slot(slot, case, key, inner, output, *, live=False, remaining=28, started=None):
    budget = LiveBudget(Scope(remaining, 1800), output)
    if started is not None:
        budget.started = started
    row = await pilot.execute(slot, case, budget,
        Scope(min(4 if slot["arm"] == "A" else 10, remaining), 600), inner,
        adapter=LiveAdapter(key, live=live))
    row["repo_sha"] = (await asyncio.to_thread(subprocess.check_output,
        ["git", "rev-parse", "HEAD"], cwd=pilot.prep.ROOT, text=True)).strip()
    row = redact_tree(row, key)
    if output:
        output.write("row.json", json.dumps(row, ensure_ascii=False))
        output.write("summary.json", json.dumps({"end_status": row["end_status"],
            "client_http_attempts": budget.run_attempts, "error_code": row.get("error_code")}))
    return row


def child(fd, run_id, output, remaining, started):
    """Called only in the sandbox-exec child, with no new network capability."""
    key = os.environ.get("CPA_API_KEY")
    private = pilot.PrivateOutput(output)
    try:
        private.write("entered.json", '{"stage":"child_ready"}')
        if not key:
            raise pilot.Stop("key_missing")
        slots, cases = frozen()
        slot = next(s for s in slots if s["run_id"] == run_id)
        with probe.isolated_environment():
            row = asyncio.run(run_slot(slot, cases[slot["case_id"]], key,
                probe.inherited_transport(fd, TARGET), private,
                live=True, remaining=remaining, started=started))
        return 0 if row["end_status"] == "PASS" else 1
    except BaseException:  # noqa: BLE001 - parent reports UNKNOWN, never raw exceptions
        return 1
    finally:
        private.close()


def read_child(path):
    """No stdout/stderr bootstrap data. Missing evidence means STOP/UNKNOWN."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        file = os.open("row.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(file) as stream:
            text = stream.read(4 * MAX_RESPONSE_BYTES + 1)
        if len(text) > 4 * MAX_RESPONSE_BYTES:
            raise pilot.Stop("child_report_limit")
        return json.loads(text)
    finally:
        os.close(fd)


def launch(output):
    slots, _ = frozen()
    key = os.environ.get("CPA_API_KEY")
    executable = shutil.which("sandbox-exec")
    if not key or not executable or sys.platform != "darwin":
        raise pilot.Stop("config_or_os_egress_unavailable")
    started = time.monotonic()
    private = pilot.PrivateOutput(output)
    rows = []
    report = {"stage": "P1-B", "status": "BLOCKED", "client_http_attempts": 0,
        "executed_slots": 0, "stop_reason": None, "human_review": "NOT RUN",
        "billing": "UNKNOWN", "upstream_retries": "UNKNOWN", "kubernetes_requests": 0,
        "manifest_sha256": pilot.prep.MANIFEST_SHA256}
    try:
        for slot in slots:
            private.write(slot["run_id"] + "-launch.json", json.dumps({
                "phase": "before_preconnect", "run_id": slot["run_id"]}))
            path = str(Path(output) / slot["run_id"])
            if time.monotonic() - started >= 1800:
                raise pilot.Stop("task_deadline")
            with socket.create_connection(("192.168.31.110", 8317), timeout=60) as conn:
                fd = conn.fileno()
                code = (f"import sys; sys.path.insert(0,{str(pilot.prep.ROOT / 'scripts')!r});"
                    f"import issue41_b1r_live_pilot as p;sys.exit(p.child({fd!r},"
                    f"{slot['run_id']!r},{path!r},{28 - report['client_http_attempts']!r},"
                    f"{started!r}))")
                report["client_http_attempts"] = "UNKNOWN"
                with probe.isolated_environment(key):
                    result = subprocess.run([executable, "-p",
                        '(version 1)(allow default)(deny network*)', sys.executable, "-I", "-c", code],
                        pass_fds=(fd,), capture_output=True, check=False,
                        timeout=min(600, max(0.01, 1800 - (time.monotonic() - started))))
                row = read_child(path)
            count = row["client_http_attempts"]
            maximum = 4 if slot["arm"] == "A" else 10
            if type(count) is not int or not 0 <= count <= maximum:
                raise pilot.Stop("child_count_contract")
            rows.append(row)
            report["executed_slots"] = len(rows)
            report["client_http_attempts"] = sum(r["client_http_attempts"] for r in rows)
            if result.returncode != 0 or row["end_status"] != "PASS":
                report["status"] = "STOP"
                report["stop_reason"] = row.get("error_code") or "child_failed"
                break
        else:
            report["status"] = "COMPLETED_PENDING_HUMAN_REVIEW"
        pilot.blind_export(rows, private)
    except BaseException as exc:  # noqa: BLE001 - no stderr, exception message or secrets
        report.update(status="BLOCKED" if not rows else "STOP",
            stop_reason="bootstrap_or_child_evidence", error_class=type(exc).__name__)
    finally:
        report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        private.write("summary.json", json.dumps(report, ensure_ascii=False, indent=2))
        private.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "COMPLETED_PENDING_HUMAN_REVIEW" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-p1b", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if not args.live_p1b or not args.output:
            raise pilot.Stop("explicit_live_config_required")
        return launch(args.output)
    except BaseException:  # noqa: BLE001 - sanitized preflight failure only
        print('{"stage":"P1-B","status":"BLOCKED","reason":"preflight"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
