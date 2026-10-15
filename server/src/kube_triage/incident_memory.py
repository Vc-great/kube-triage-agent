"""Bounded, review-only historical Pod incident records for the single-user demo.

DEMO_WORKFLOW_ONLY: the same API key can start a Run and approve its interrupt.
Aegra's get_auth_ctx is an internal API verified against aegra-cli 0.10.8;
revalidate it before upgrading Aegra.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

import yaml
from aegra_api.core.auth_ctx import get_auth_ctx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kube_triage.config import incident_memory_provenance_key
from kube_triage.mcp_client import NAMESPACE, POD_NAME

STORE_ROOT = "kube-triage"
SCHEMA_VERSION = 1
MEMORY_ID = re.compile(r"^[0-9a-f]{32}$")
SAFE_UID = re.compile(r"^[A-Za-z0-9-]{1,128}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
UNTRUSTED_MARKERS = ("<system", "</system", "忽略指令", "执行 scale", "bearer ",
                     "authorization:", "private key", "api_token")
SYMPTOMS = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "OOMKilled",
            "CreateContainerConfigError", "Pending", "Failed", "Unknown"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def owner() -> str:
    identity = getattr(getattr(get_auth_ctx(), "user", None), "identity", None)
    if identity != "demo-user":
        raise PermissionError("Missing trusted demo identity")
    return identity


def store_namespace(identity: str) -> tuple[str, ...]:
    if identity != "demo-user":
        raise PermissionError("Invalid demo identity")
    return (STORE_ROOT, identity, "incidents", "v1")


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def make_attestation(human: HumanMessage, ai: AIMessage, call: dict,
                     tool: ToolMessage, thread_id: str) -> dict:
    """Called only by the server's tools node after a real Reader response."""
    if not all(_valid_id(x) for x in (human.id, ai.id, call.get("id"), tool.id, thread_id)):
        raise ValueError("missing_attestation_id")
    body = {"thread_id": thread_id, "human_id": human.id, "ai_id": ai.id,
            "tool_id": tool.id, "tool_call_id": call["id"],
            "tool_name": tool.name, "tool_status": tool.status,
            "call_name": call.get("name"), "call_args": call.get("args"),
            "content_sha256": hashlib.sha256(str(tool.content).encode("utf-8")).hexdigest()}
    mac = hmac.new(incident_memory_provenance_key(), canonical(body).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return {**body, "mac": mac}


def _attested(attestations: object, human: HumanMessage, ai: AIMessage, call: dict,
              tool: ToolMessage, thread_id: str) -> bool:
    if not isinstance(attestations, list) or len(attestations) > 6:
        return False
    expected = make_attestation(human, ai, call, tool, thread_id)
    return any(isinstance(item, dict) and set(item) == set(expected)
               and all(item[key] == value for key, value in expected.items() if key != "mac")
               and isinstance(item.get("mac"), str)
               and hmac.compare_digest(item["mac"], expected["mac"])
               for item in attestations)


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def _valid_utc(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


def _ordinary_last_round(messages: list) -> tuple[HumanMessage, list]:
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise ValueError("missing_command")
    last = next((i for i in range(len(messages) - 2, -1, -1)
                 if isinstance(messages[i], HumanMessage)), None)
    if last is None:
        raise ValueError("missing_diagnosis")
    start = next((i for i in range(last - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), None)
    round_messages = messages[last + 1:len(messages) - 1]
    human = messages[last]
    if (not isinstance(human.content, str) or human.content.lstrip().startswith("/")
            or start is not None and any(isinstance(m, HumanMessage)
                                         for m in messages[start + 1:last])):
        raise ValueError("not_ordinary_diagnosis")
    if (not round_messages or not isinstance(round_messages[-1], AIMessage)
            or round_messages[-1].name != "triage_llm"
            or round_messages[-1].tool_calls or not round_messages[-1].content):
        raise ValueError("incomplete_diagnosis")
    if any(not isinstance(m, (AIMessage, ToolMessage)) for m in round_messages):
        raise ValueError("invalid_round")
    return human, round_messages


def extract_candidate(messages: list, thread_id: str, identity: str,
                      memory_id: str | None = None,
                      attestations: list | None = None) -> dict:
    """Use only paired successful pods_get from the immediately preceding turn.

    This projects safe fields from a structured Pod; no raw result, logs, model
    text, labels, annotations, environment variables or stack traces are copied.
    """
    if not _valid_id(thread_id) or identity != "demo-user":
        raise ValueError("invalid_source")
    human, round_messages = _ordinary_last_round(messages)
    calls: dict[str, tuple[AIMessage, dict, int]] = {}
    for index, message in enumerate(round_messages):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            call_id = call.get("id")
            if not _valid_id(call_id) or call_id in calls:
                raise ValueError("invalid_tool_call_id")
            calls[call_id] = (message, call, index)
    if not calls:
        raise ValueError("no_tool_calls")
    paired = []
    seen = set()
    for index, message in enumerate(round_messages):
        if not isinstance(message, ToolMessage):
            continue
        pair = calls.get(message.tool_call_id)
        if (pair is None or message.tool_call_id in seen or
                message.name != pair[1]["name"] or index <= pair[2]):
            raise ValueError("unpaired_tool_result")
        seen.add(message.tool_call_id)
        if pair[1]["name"] == "pods_get":
            paired.append((pair[0], pair[1], message))
    if seen != set(calls):
        raise ValueError("incomplete_tool_results")
    if len(paired) != 1:
        raise ValueError("ambiguous_pod_evidence")
    ai, call, tool = paired[0]
    if not _attested(attestations, human, ai, call, tool, thread_id):
        raise ValueError("untrusted_reader_receipt")
    args = call.get("args")
    if (not isinstance(args, dict) or set(args) != {"namespace", "name"}
            or args.get("namespace") != NAMESPACE
            or not isinstance(args.get("name"), str)
            or not POD_NAME.fullmatch(args["name"])):
        raise ValueError("invalid_tool_target")
    if (tool.status != "success" or not isinstance(tool.content, str)
            or len(tool.content) > 20_000 or not _valid_id(ai.id)
            or not _valid_id(tool.id)):
        raise ValueError("invalid_tool_result")
    lowered = tool.content.lower()
    if any(marker in lowered for marker in UNTRUSTED_MARKERS):
        raise ValueError("unsafe_tool_result")
    try:
        envelope = json.loads(tool.content)
        if (not isinstance(envelope, dict) or envelope.get("ok") is not True
                or not isinstance(envelope.get("result"), str)
                or not envelope["result"].strip() or len(envelope["result"]) > 16_384):
            raise ValueError("invalid_envelope")
        pod = yaml.safe_load(envelope["result"])
    except (json.JSONDecodeError, yaml.YAMLError, TypeError) as exc:
        raise ValueError("invalid_pod") from exc
    if not isinstance(pod, dict) or pod.get("kind") != "Pod":
        raise ValueError("invalid_pod")
    metadata = pod.get("metadata")
    if (not isinstance(metadata, dict) or metadata.get("name") != args["name"]
            or metadata.get("namespace") != NAMESPACE):
        raise ValueError("target_mismatch")
    uid = metadata.get("uid")
    if uid is not None and (not isinstance(uid, str) or not SAFE_UID.fullmatch(uid)):
        raise ValueError("invalid_uid")
    pod_status = pod.get("status")
    if not isinstance(pod_status, dict):
        raise TypeError("missing_status")
    reasons = set()
    for container in pod_status.get("containerStatuses") or []:
        if not isinstance(container, dict):
            raise TypeError("invalid_status")
        state = container.get("state") or {}
        if not isinstance(state, dict):
            raise TypeError("invalid_status")
        reason = (state.get("waiting") or {}).get("reason") if isinstance(
            state.get("waiting") or {}, dict) else None
        if reason in SYMPTOMS:
            reasons.add(reason)
    phase = pod_status.get("phase")
    if not reasons and phase in SYMPTOMS:
        reasons.add(phase)
    if len(reasons) != 1:
        raise ValueError("ambiguous_symptom")
    symptom = next(iter(reasons))
    memory_id = memory_id or uuid4().hex
    candidate = {
        "schema_version": SCHEMA_VERSION, "memory_id": memory_id, "owner": identity,
        "namespace": NAMESPACE, "resource_kind": "Pod", "resource_name": args["name"],
        "observed_uid": uid, "workload_kind": None, "workload_name": None,
        "symptom": symptom,
        "observations": [f"pods_get 确认该 Pod 当时状态为 {symptom}。"],
        "cause_hypothesis": None, "uncertainties": ["尚未确定根因；历史状态不是当前证据。"],
        "observed_at": None,
        "source": {"thread_id": thread_id, "message_ids": [human.id, ai.id, tool.id],
                   "tool_call_ids": [call["id"]], "evidence_types": ["pods_get"]},
    }
    validate_candidate(candidate, identity, thread_id)
    return candidate


def validate_candidate(candidate: dict, identity: str, thread_id: str) -> None:
    expected = {"schema_version", "memory_id", "owner", "namespace", "resource_kind",
                "resource_name", "observed_uid", "workload_kind", "workload_name", "symptom",
                "observations", "cause_hypothesis", "uncertainties", "observed_at", "source"}
    if not isinstance(candidate, dict) or set(candidate) != expected:
        raise ValueError("candidate_fields")
    source = candidate["source"]
    if (candidate["schema_version"] != SCHEMA_VERSION or
            not isinstance(candidate["schema_version"], int) or
            not isinstance(candidate["memory_id"], str) or
            not MEMORY_ID.fullmatch(candidate["memory_id"]) or
            candidate["owner"] != identity or candidate["namespace"] != NAMESPACE or
            candidate["resource_kind"] != "Pod" or
            not isinstance(candidate["resource_name"], str) or
            not POD_NAME.fullmatch(candidate["resource_name"]) or
            candidate["symptom"] not in SYMPTOMS or
            candidate["observed_uid"] is not None and (
                not isinstance(candidate["observed_uid"], str) or
                not SAFE_UID.fullmatch(candidate["observed_uid"])) or
            any(candidate[key] is not None for key in (
                "workload_kind", "workload_name", "cause_hypothesis", "observed_at")) or
            candidate["observations"] != [
                f"pods_get 确认该 Pod 当时状态为 {candidate['symptom']}。"] or
            candidate["uncertainties"] != ["尚未确定根因；历史状态不是当前证据。"] or
            not isinstance(source, dict) or set(source) != {
                "thread_id", "message_ids", "tool_call_ids", "evidence_types"} or
            source["thread_id"] != thread_id or source["evidence_types"] != ["pods_get"] or
            not isinstance(source["message_ids"], list) or len(source["message_ids"]) != 3 or
            not all(_valid_id(x) for x in source["message_ids"]) or
            not isinstance(source["tool_call_ids"], list) or
            len(source["tool_call_ids"]) != 1 or
            not _valid_id(source["tool_call_ids"][0])):
        raise ValueError("invalid_candidate")
    canonical(candidate)


def approved_record(candidate: dict, identity: str, thread_id: str) -> dict:
    validate_candidate(candidate, identity, thread_id)
    now = utc_now()
    return {**candidate, "recorded_at": now,
            "review": {"status": "user_reviewed", "reviewer": identity, "reviewed_at": now},
            "status": "active"}


def validate_record(record: dict, identity: str, thread_id: str) -> None:
    if not isinstance(record, dict) or set(record) != {
            "schema_version", "memory_id", "owner", "namespace", "resource_kind",
            "resource_name", "observed_uid", "workload_kind", "workload_name", "symptom",
            "observations", "cause_hypothesis", "uncertainties", "observed_at", "source",
            "recorded_at", "review", "status"}:
        raise ValueError("record_fields")
    validate_candidate({key: value for key, value in record.items()
                        if key not in {"recorded_at", "review", "status"}}, identity, thread_id)
    review = record["review"]
    if (not _valid_utc(record["recorded_at"]) or
            not isinstance(review, dict) or set(review) != {
                "status", "reviewer", "reviewed_at"} or
            review["status"] != "user_reviewed" or review["reviewer"] != identity or
            not _valid_utc(review["reviewed_at"]) or record["status"] != "active"):
        raise ValueError("invalid_review")


async def commit(store, record: dict, identity: str, thread_id: str) -> str:
    validate_record(record, identity, thread_id)
    ns = store_namespace(identity)
    key = record["memory_id"]
    try:
        old = await store.aget(ns, key)
        if old:
            return "already_committed" if old.value == record else "conflict"
        await store.aput(ns, key, record)
        saved = await store.aget(ns, key)
        return "stored" if saved and saved.value == record else "unknown"
    except Exception:  # noqa: BLE001 - lost write receipt cannot prove absence
        return "unknown"


async def revoke(store, memory_id: str, expected_hash: str, identity: str) -> str:
    if not isinstance(memory_id, str) or not MEMORY_ID.fullmatch(memory_id):
        return "rejected"
    ns = store_namespace(identity)
    try:
        old = await store.aget(ns, memory_id)
        if not old or not isinstance(old.value, dict) or old.value.get("owner") != identity:
            return "rejected"
        if old.value.get("status") == "revoked":
            return "already_revoked"
        try:
            validate_record(old.value, identity, old.value["source"]["thread_id"])
        except (ValueError, TypeError, KeyError):
            return "rejected"
        if old.value.get("status") != "active" or digest(old.value) != expected_hash:
            return "conflict"
        updated = {**old.value, "status": "revoked", "revoked_at": utc_now(),
                   "revoked_by": identity}
        await store.aput(ns, memory_id, updated)
        saved = await store.aget(ns, memory_id)
        return "revoked" if saved and saved.value == updated else "unknown"
    except Exception:  # noqa: BLE001 - uncertain network result
        return "unknown"
