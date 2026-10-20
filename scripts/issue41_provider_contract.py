"""P0 candidate Chat Completions adapter: MockTransport only, never live authority.

This module deliberately has no network transport factory or credential input.
Synthetic reservations validate control flow, not real tokens or billing. P1
requires a separate reviewed implementation, evidence and explicit authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import re
import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import issue41_b1r_pilot as pilot

LOCKED = {"openai": "3.29.0", "langchain-openai": "1.7.0", "httpx": "0.28.1"}


@dataclass(frozen=True)
class ProviderProfile:
    """Non-secret contract specification; evidence references are never approvals.

    No real provider is selected. All optional evidence is UNKNOWN until checked
    independently; even populated fields cannot enable a live transport in P0.
    """
    provider: str
    endpoint: str
    request_model: str
    echo_model: str
    max_output: int
    api_version: str = "chat-completions"
    tls_verify: bool = True
    max_retries: int = 0
    tokenizer_evidence: str | None = None
    output_reasoning_evidence: str | None = None
    usage_semantics_evidence: str | None = None
    dated_price_currency_evidence: str | None = None
    failure_billing_evidence: str | None = None
    upstream_retry_evidence: str | None = None
    provider_spend_cap_evidence: str | None = None

    def __post_init__(self):
        url = urlsplit(self.endpoint)
        if (url.scheme != "https" or not url.hostname
                or not re.fullmatch(r"[a-z0-9]+(?:[-.][a-z0-9]+)*\.[a-z]{2,}", url.hostname)
                or url.port not in (None, 443) or url.username or url.password
                or url.query or url.fragment or url.path != "/v1/chat/completions"
                or self.endpoint != f"https://{url.hostname}/v1/chat/completions"
                or self.tls_verify is not True):
            raise ValueError("endpoint_or_tls_contract")
        if (not self.provider or not self.request_model or not self.echo_model
                or self.api_version != "chat-completions" or self.max_retries != 0
                or type(self.max_output) is not int or not 1 <= self.max_output <= 512):
            raise ValueError("provider_contract")

    def live_gate(self):
        # Not a bool derived from user-supplied evidence strings or CLI flags.
        return {"status": "BLOCKED", "authorization": "P0_OFFLINE_ONLY",
                "real_usage": "UNKNOWN", "real_cost": "UNKNOWN",
                "tokenizer": "UNKNOWN", "upstream_retry": "UNKNOWN",
                "os_egress_policy_for_live": "NOT VERIFIED", "B8": "NOT RUN"}


def synthetic_profile():
    return ProviderProfile("synthetic-contract-fixture", "https://contract.invalid/v1/chat/completions",
                           "contract-request-model", "contract-echo-model", 512)


class ContractBudget(pilot.Budget):
    """Retain receipt/safety/decision rules. Reservations remain SYNTHETIC."""
    def __init__(self, total, profile):
        super().__init__(total)
        self.OUTPUT = profile.max_output
        self.in_flight = False


class OfflineAdapter:
    def __init__(self, profile):
        self.profile = profile
        if any(importlib.metadata.version(name) != version for name, version in LOCKED.items()):
            raise pilot.Stop("sdk_version_contract")

    def make_model(self, client, budget, case):
        return pilot.make_model(client, budget, case, model_options={
            "model": self.profile.request_model,
            "base_url": self.profile.endpoint.removesuffix("/chat/completions"),
            "max_retries": self.profile.max_retries})

    def guarded_transport(self, inner, budget):
        # Only exact in-memory HTTP fake. Never instantiate HTTP(S)Transport.
        if type(inner) is not httpx.MockTransport:
            budget.stop("p0_mock_transport_only")
        profile = self.profile

        class Guard(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                budget.check()
                if budget.in_flight:
                    budget.stop("parallel_http_disabled")
                budget.in_flight = True
                audit = None
                try:
                    body = json.loads(request.content)
                    allowed_tools = pilot.prep.READERS | ({"write_todos"} if budget.arm == "B"
                                                         else set())
                    tools = body.get("tools", [])
                    if (str(request.url) != profile.endpoint or request.method != "POST"
                            or request.headers.get("host") != request.url.host
                            or request.headers.get("content-type") != "application/json"
                            or body.get("model") != profile.request_model
                            or body.get("stream", False) is not False
                            or body.get("n", 1) != 1
                            or body.get("max_completion_tokens") != profile.max_output
                            or "max_tokens" in body or "reasoning_effort" in body
                            or not isinstance(body.get("messages"), list)
                            or not isinstance(tools, list) or any(
                                t.get("type") != "function"
                                or t.get("function", {}).get("name") not in allowed_tools
                                for t in tools)):
                        budget.stop("request_contract")
                    budget.reserve()  # No await until both global/per-Run reservations commit.
                    audit = {"attempt": budget.attempts, "status": "UNKNOWN", "usage": None,
                             "actual_cost": "UNKNOWN", "reservation_currency": "SYNTHETIC"}
                    budget.audit.append(audit)
                    async with asyncio.timeout(min(budget.deadline - pilot.time.monotonic(),
                            budget.total.seconds - (pilot.time.monotonic() - budget.started))):
                        response = await inner.handle_async_request(request)
                        await response.aread()
                    budget.check()
                    audit["status"] = response.status_code
                    if not response.is_success:
                        budget.stop("redirect_disabled" if response.is_redirect else "http_failure")
                    data = response.json()
                    budget.model_echoed = data.get("model")
                    if budget.model_echoed != profile.echo_model:
                        budget.stop("model_echo")
                    usage = data.get("usage")
                    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int
                            or usage[k] < 0 for k in
                            ("prompt_tokens", "completion_tokens", "total_tokens")):
                        budget.stop("usage_unknown")
                    if (usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
                            or usage["prompt_tokens"] > budget.INPUT
                            or usage["completion_tokens"] > budget.OUTPUT):
                        budget.stop("usage_outside_reservation")
                    for key, field, maximum in (
                        ("prompt_tokens_details", "cached_tokens", usage["prompt_tokens"]),
                        ("completion_tokens_details", "reasoning_tokens", usage["completion_tokens"]),
                    ):
                        details = usage.get(key)
                        if details is not None and (not isinstance(details, dict)
                                or type(details.get(field)) is not int
                                or not 0 <= details[field] <= maximum):
                            budget.stop("usage_details_unknown")
                    choices = data.get("choices")
                    if not isinstance(choices, list) or len(choices) != 1:
                        budget.stop("generation_count")
                    audit["usage"] = usage
                    return response
                except BaseException:
                    # Sticky before SDK retry: any retry re-enters check(), never the fake.
                    budget.reason = budget.reason or "transport_or_response_error"
                    raise
                finally:
                    budget.in_flight = False

        return Guard()

    def annotate(self, row):
        row.update(model_requested=self.profile.request_model,
                   endpoint_class="P0-contract-mock-only", usage_source="synthetic_sdk",
                   provider_contract=self.profile.live_gate(),
                   real_provider_usage="UNKNOWN", actual_cost="UNKNOWN",
                   provider_config_fingerprint=pilot.hashlib.sha256(
                       repr(self.profile).encode()).hexdigest())


def synthetic_transport(case, slot, profile):
    """Reuse frozen scripted replies and HTTP formatter; only model echo differs."""
    inner = pilot.synthetic_http(pilot.prep._scripted_model(case, slot["run_id"], slot["arm"]).replies)

    async def handler(request):
        response = await inner.handle_async_request(request)
        data = response.json()
        data["model"] = profile.echo_model
        return httpx.Response(response.status_code, json=data)

    return httpx.MockTransport(handler)


async def run_contract(output, total=None, per_run=None):
    manifest, cases = pilot.prep._load_frozen()
    profile = synthetic_profile()
    adapter = OfflineAdapter(profile)
    budget = ContractBudget(total or pilot.Limits(), profile)
    rows = []
    repo_sha = (await asyncio.to_thread(subprocess.check_output, ["git", "rev-parse", "HEAD"],
                                       cwd=pilot.prep.ROOT, text=True)).strip()
    for slot in pilot.pilot_slots(manifest):
        row = await pilot.execute(slot, cases[slot["case_id"]], budget, per_run or pilot.Limits(),
            synthetic_transport(cases[slot["case_id"]], slot, profile), adapter=adapter)
        row["repo_sha"] = repo_sha
        rows.append(row)
        output.write(slot["run_id"] + ".json", json.dumps(row, ensure_ascii=False))
        if row["end_status"] != "PASS":
            break
    pilot.blind_export(rows, output)
    return {"repo_sha": repo_sha, "stage": "P0_OFFLINE_CONTRACT", "status": "PASS" if len(rows) == 4
            and not budget.reason else "STOP", "stop_reason": budget.reason,
            "completed_slots": len(rows), "simulated_http_attempts": budget.attempts,
            "provider_requests": 0, "kubernetes_requests": 0, "human_review": "NOT RUN",
            "manifest_sha256": pilot.prep.MANIFEST_SHA256, "live_gate": profile.live_gate()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-contract", action="store_true", required=True)
    parser.add_argument("--output", required=True, help="new absolute private directory")
    parser.add_argument("--simulate-budget", action="store_true")
    args = parser.parse_args()
    output = None
    try:
        with pilot.offline():
            output = pilot.PrivateOutput(args.output)
            n = 32 if args.simulate_budget else 0
            limits = pilot.Limits(n, n * (pilot.Budget.INPUT + 512),
                                 n * (pilot.Budget.INPUT + 512) * pilot.Budget.RATE)
            result = asyncio.run(run_contract(output, limits, limits))
            output.write("summary.json", json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1
    except Exception:  # noqa: BLE001 - never print request, provider error or environment
        print('{"status":"STOP","error_code":"offline_contract_error"}')
        return 1
    finally:
        if output is not None:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
