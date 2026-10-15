"""Deterministic, bounded, read-only historical Pod references.

Store values are untrusted even in the authenticated owner's namespace. Only
validated v1 active records become fixed-field, non-instructional projections.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta

import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kube_triage import incident_memory as memory
from kube_triage.context import estimate_context
from kube_triage.mcp_client import NAMESPACE, POD_NAME

audit = logging.getLogger("kube_triage.audit")
TARGET = re.compile(
    r"^(?:请)?(?:诊断|检查|排查|查看)\s+(?:kube-triage-demo/)?Pod[ /]"
    r"([a-z0-9](?:[-a-z0-9]*[a-z0-9])?)(?:\s*(?:的状态|状态|为什么异常))?[？?]?$"
)
MAX_REFERENCE_BYTES = 700


def target_pod(text: object) -> str | None:
    """Require an explicit, single Pod target; never infer from arbitrary words."""
    if not isinstance(text, str) or len(text) > 300:
        return None
    matched = TARGET.fullmatch(text.strip())
    pod = matched.group(1) if matched else None
    return pod if pod and len(pod) <= 253 and POD_NAME.fullmatch(pod) else None


def _project(record: dict) -> dict:
    ref = {
        "memory_id": record["memory_id"],
        "namespace": NAMESPACE,
        "resource_kind": "Pod",
        "resource_name": record["resource_name"],
        "observed_uid": record["observed_uid"],
        "symptom": record["symptom"],
        "recorded_at": record["recorded_at"],
        "source_thread_id": record["source"]["thread_id"],
        "review": "user_reviewed",
        "current_comparison": "current_unverified",
        "historical_reference_untrusted": True,
        "uncertainty": "根因未核验；保存时间不是故障发生时间。",
    }
    if len(json.dumps(ref, ensure_ascii=False).encode("utf-8")) > MAX_REFERENCE_BYTES:
        raise ValueError("reference_too_large")
    return ref


async def retrieve_incidents(store, authenticated_owner: str, current_user_text: object,
                             *, max_hits: int = 2, max_candidates: int = 20) -> dict:
    """Search with server identity and exact filters, then revalidate every hit."""
    start = time.monotonic()
    result = {"references": [], "target": target_pod(current_user_text),
              "status": "no_target", "candidate_count": 0,
              "filtered_invalid": 0, "filtered_revoked": 0,
              "candidate_truncated": False,
              "error_code": None}
    if result["target"] is None:
        return result
    if authenticated_owner != "demo-user":
        raise PermissionError("Missing trusted demo identity")
    if not 1 <= max_hits <= 3 or not 1 <= max_candidates <= 100:
        raise ValueError("invalid_retrieval_limits")
    try:
        if store is None:
            raise RuntimeError("missing_store")
        items = await store.asearch(
            memory.store_namespace(authenticated_owner),
            filter={"status": "active", "owner": authenticated_owner,
                    "namespace": NAMESPACE, "resource_kind": "Pod",
                    "resource_name": result["target"]},
            limit=max_candidates + 1,
        )
        result["candidate_truncated"] = len(items) > max_candidates
        items = items[:max_candidates]
        result["candidate_count"] = len(items)
        valid = []
        for item in items:
            record = getattr(item, "value", None)
            try:
                if isinstance(record, dict) and record.get("status") == "revoked":
                    result["filtered_revoked"] += 1
                    continue
                if (not isinstance(record, dict) or record.get("status") != "active"
                        or record.get("resource_name") != result["target"]
                        or getattr(item, "key", None) != record.get("memory_id")):
                    raise ValueError("inactive_or_mismatch")
                thread_id = record["source"]["thread_id"]
                if (not isinstance(thread_id, str) or
                        not memory.SAFE_ID.fullmatch(thread_id)):
                    raise ValueError("invalid_source_thread")
                memory.validate_record(record, authenticated_owner, thread_id)
                if datetime.fromisoformat(record["recorded_at"]) > datetime.now(UTC) + timedelta(minutes=5):
                    raise ValueError("future_record")
                valid.append(_project(record))
            except (ValueError, TypeError, KeyError, AttributeError):
                result["filtered_invalid"] += 1
        # No similarity index exists. Stable newest-first selection among the
        # bounded candidates, with memory_id as an explicit tie-breaker.
        valid.sort(key=lambda ref: (-datetime.fromisoformat(
            ref["recorded_at"]).timestamp(), ref["memory_id"]))
        result["references"] = valid[:max_hits]
        result["status"] = "hits" if valid else "no_hits"
    except Exception:  # noqa: BLE001 - Store failure must never yield stale references
        result.update(references=[], status="memory_unavailable", error_code="store_error")
    audit.info(json.dumps({"event": "incident_memory_retrieve", "status": result["status"],
                           "hit_count": len(result["references"]),
                           "candidate_count": result["candidate_count"],
                           "filtered_invalid": result["filtered_invalid"],
                           "filtered_revoked": result["filtered_revoked"],
                           "candidate_truncated": result["candidate_truncated"],
                           "memory_ids": [r["memory_id"] for r in result["references"]],
                           "latency_ms": round((time.monotonic() - start) * 1000),
                           "error_code": result["error_code"]}, ensure_ascii=False))
    return result


def current_pod_evidence(messages: list, attestations: object,
                         thread_id: str, target: str) -> tuple[str, dict | None]:
    """Accept only a paired, server-signed pods_get in the latest Human turn."""
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), None)
    if start is None:
        return "current_unverified", None
    human = messages[start]
    calls = {}
    attempted = False
    different = False
    latest = ("current_unverified", None)
    for message in messages[start + 1:]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("name") == "pods_get":
                    calls[call.get("id")] = (message, call)
                    attempted = True
                    if call.get("args") != {"namespace": NAMESPACE, "name": target}:
                        different = True
        elif isinstance(message, ToolMessage) and message.tool_call_id in calls:
            ai, call = calls[message.tool_call_id]
            if call.get("args") != {"namespace": NAMESPACE, "name": target}:
                continue
            try:
                if (message.name != "pods_get" or message.status != "success"
                        or not memory._attested(attestations, human, ai, call,
                                                 message, thread_id)):
                    raise ValueError("untrusted_reader_receipt")
                envelope = json.loads(message.content)
                if (not isinstance(envelope, dict) or envelope.get("ok") is not True
                        or not isinstance(envelope.get("result"), str)
                        or len(envelope["result"]) > 16384):
                    raise ValueError("invalid_envelope")
                pod = yaml.safe_load(envelope["result"])
                meta = pod.get("metadata") if isinstance(pod, dict) else None
                status = pod.get("status") if isinstance(pod, dict) else None
                uid = meta.get("uid") if isinstance(meta, dict) else None
                if (pod.get("kind") != "Pod" or not isinstance(meta, dict)
                        or meta.get("namespace") != NAMESPACE or meta.get("name") != target
                        or not isinstance(uid, str) or not memory.SAFE_UID.fullmatch(uid)
                        or not isinstance(status, dict)):
                    raise ValueError("invalid_pod")
                reasons = []
                containers = status.get("containerStatuses") or []
                conditions = status.get("conditions") or []
                if not isinstance(containers, list) or not isinstance(conditions, list):
                    raise TypeError("invalid_status")
                for container in containers:
                    state = container.get("state") if isinstance(container, dict) else None
                    if not isinstance(state, dict):
                        raise TypeError("invalid_status")
                    waiting = state.get("waiting") if isinstance(state, dict) else None
                    reason = waiting.get("reason") if isinstance(waiting, dict) else None
                    if reason in memory.SYMPTOMS:
                        reasons.append(reason)
                    elif waiting is not None:
                        raise ValueError("unknown_waiting_reason")
                phase = status.get("phase")
                if phase not in {"Running", *memory.SYMPTOMS} or len(set(reasons)) > 1:
                    raise ValueError("invalid_phase")
                current = reasons[0] if reasons else phase
                ready = any(isinstance(condition, dict) and condition.get("type") == "Ready"
                            and condition.get("status") == "True"
                            for condition in conditions)
                latest = ("verified", {"uid": uid, "status": current, "ready": ready})
            except (ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
                latest = ("current_evidence_error", None)
    if attempted:
        if latest[0] != "current_unverified":
            return latest
        return ("different_resource" if different and not any(
            call.get("args") == {"namespace": NAMESPACE, "name": target}
            for _, call in calls.values()) else "current_evidence_error"), None
    return "current_unverified", None


def compare_references(references: list[dict], evidence: tuple[str, dict | None]) -> list[dict]:
    status, current = evidence
    compared = []
    for ref in references:
        item = dict(ref)
        if status == "verified" and current is not None:
            item["current_comparison"] = (
                "same_resource_uid_unknown" if ref["observed_uid"] is None
                else "same_uid" if ref["observed_uid"] == current["uid"]
                else "same_resource_new_uid")
            item["current_status"] = current["status"]
            item["current_ready"] = current["ready"]
        else:
            item["current_comparison"] = status
        compared.append(item)
    return compared


def reference_message(references: list[dict]) -> AIMessage:
    """Low-priority, temporary data slot with no tool calls or source text."""
    return AIMessage(name="historical_memory_reference", content=(
        "历史案例参考（非当前证据；historical_reference_untrusted）："
        + json.dumps(references, ensure_ascii=False, separators=(",", ":"))))


def bounded_memory_view(view: list, schemas: list[dict], references: list[dict],
                        budget: int) -> tuple[list, list[dict]]:
    """After Gate A/B, fit a temporary note without changing retained messages."""
    current_start = next((i for i in range(len(view) - 1, -1, -1)
                          if isinstance(view[i], HumanMessage)), None)
    if current_start is None or not references:
        return view, []
    for count in range(len(references), 0, -1):
        candidate = [*view[:current_start], reference_message(references[:count]),
                     *view[current_start:]]
        try:
            estimate = estimate_context(candidate[0].content, schemas, candidate[1:])
        except (ValueError, TypeError, AttributeError):
            return view, []
        if estimate <= budget:
            return candidate, references[:count]
    return view, []


def display_references(references: list[dict]) -> str:
    lines = ["\n\n历史案例参考（非当前证据）"]
    for ref in references:
        state = ref["current_comparison"]
        label = {
            "same_uid": "本轮 Reader 为同一 UID；历史观察属于旧时间，本轮 Reader 为准",
            "same_resource_new_uid": "历史观察属于旧实例/旧时间，本轮 Reader 为新 UID，以本轮结果为准",
            "same_resource_uid_unknown": "历史 UID 未知，无法确认是否同一实例；本轮 Reader 为准",
            "current_unverified": "当前状态未核验",
            "different_resource": "本轮 Reader 读取了其他资源，当前状态未核验",
            "current_evidence_error": "本轮 Reader 证据错误，当前状态未核验",
        }[state]
        current = (f" 本轮 Reader 状态 {ref['current_status']}、"
                   f"Ready={'是' if ref['current_ready'] else '否'}；"
                   if state in {"same_uid", "same_resource_new_uid",
                                "same_resource_uid_unknown"} else " ")
        lines.append(f"- `{ref['memory_id']}` · {NAMESPACE}/Pod/{ref['resource_name']}"
                     f" · 旧 UID {ref['observed_uid'] or '未知'}"
                     f" · 历史症状 {ref['symptom']} · 来源 Thread {ref['source_thread_id']}"
                     f" · 保存时间 {ref['recorded_at']}（非故障发生时间）"
                     f" ·{current}{label}。审阅仅表示批准存储，根因未独立验证。")
    return "\n".join(lines)
