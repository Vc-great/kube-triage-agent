"""Independent Memory and revoke interrupts; never routes into Repair."""

from __future__ import annotations

import json
import logging
import time

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from kube_triage import incident_memory as memory
from kube_triage.config import incident_memory_write_enabled

audit = logging.getLogger("kube_triage.audit")


def _thread(config: RunnableConfig) -> str:
    thread_id = config.get("configurable", {}).get("thread_id")
    if not isinstance(thread_id, str) or not memory.SAFE_ID.fullmatch(thread_id):
        raise ValueError("invalid_thread")
    return thread_id


def _reply(status: str, message: str, **updates) -> dict:
    return {**updates, "memory_status": status, "messages": [AIMessage(content=message)]}


def _audit(event: str, key: str | None, status: str, start: float) -> None:
    audit.info(json.dumps({"event": event, "memory_id": key, "status": status,
                           "duration_ms": round((time.monotonic() - start) * 1000)}))


def prepare(state: dict, config: RunnableConfig) -> dict:
    if not incident_memory_write_enabled():
        return _reply("disabled", "Incident Memory 未启用；没有读取或写入 Memory Store。",
                      memory_candidate=None, memory_hash=None, memory_record=None)
    try:
        identity = memory.owner()
        candidate = memory.extract_candidate(state["messages"], _thread(config), identity,
                                             attestations=state.get("reader_attestations"))
        candidate_hash = memory.digest(candidate)
    except (ValueError, PermissionError, TypeError, KeyError):
        return _reply("rejected", "紧邻命令前的完整诊断缺少可核对的 pods_get 证据；未生成候选。",
                      memory_candidate=None, memory_hash=None, memory_record=None)
    return {"memory_candidate": candidate, "memory_hash": candidate_hash,
            "memory_record": None, "memory_status": "pending"}


def review(state: dict, config: RunnableConfig) -> dict:
    candidate = state.get("memory_candidate")
    candidate_hash = state.get("memory_hash")
    if state.get("memory_status") != "pending" or not isinstance(candidate, dict):
        return _reply("rejected", "Memory 审阅状态无效；没有保存。")
    # The interrupt can replay this node; there are no writes or random IDs before it.
    decision = interrupt({"kind": "incident_memory_review", "candidate_id": candidate["memory_id"],
                          "candidate_hash": candidate_hash, "schema_version": memory.SCHEMA_VERSION,
                          "preview": candidate, "options": ["approve", "reject"],
                          "notice": "DEMO_WORKFLOW_ONLY：历史参考，不是当前 Kubernetes 证据，也不授权修复。"})
    expected_keys = {"kind", "candidate_id", "candidate_hash", "schema_version", "decision"}
    try:
        identity, thread_id = memory.owner(), _thread(config)
        source = memory.extract_candidate(state["messages"], thread_id, identity,
                                          candidate["memory_id"], state.get("reader_attestations"))
        valid = (isinstance(decision, dict) and set(decision) == expected_keys
                 and decision.get("kind") == "incident_memory_review"
                 and type(decision.get("schema_version")) is int
                 and decision["schema_version"] == memory.SCHEMA_VERSION
                 and decision.get("candidate_id") == candidate["memory_id"]
                 and decision.get("candidate_hash") == candidate_hash
                 and decision.get("decision") == "approve"
                 and source == candidate and memory.digest(source) == candidate_hash)
    except (ValueError, PermissionError, TypeError, KeyError):
        valid = False
    if not valid:
        return _reply("rejected", "Memory 审批拒绝或参数/来源无效；没有保存。",
                      memory_record=None)
    record = memory.approved_record(candidate, identity, thread_id)
    return {"memory_status": "approved", "memory_record": record}


async def commit(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    start = time.monotonic()
    candidate = state.get("memory_candidate")
    key = candidate.get("memory_id") if isinstance(candidate, dict) else None
    status = "rejected"
    try:
        if not incident_memory_write_enabled() or state.get("memory_status") != "approved":
            raise ValueError("not_approved")
        identity, thread_id = memory.owner(), _thread(config)
        source = memory.extract_candidate(state["messages"], thread_id, identity, key,
                                          state.get("reader_attestations"))
        if source != candidate or memory.digest(source) != state.get("memory_hash"):
            raise ValueError("source_changed")
        record = state.get("memory_record")
        memory.validate_record(record, identity, thread_id)
        if record["memory_id"] != key or runtime.store is None:
            raise ValueError("invalid_store")
        status = await memory.commit(runtime.store, record, identity, thread_id)
    except (ValueError, PermissionError, TypeError, KeyError):
        pass
    _audit("incident_memory_commit", key, status, start)
    return _reply(status, f"Incident Memory 保存结果：{status}。历史参考不代表当前状态。")


async def revoke_prepare(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    if not incident_memory_write_enabled():
        return _reply("disabled", "Incident Memory 未启用；没有访问 Memory Store。",
                      revoke_request=None)
    try:
        identity, thread_id = memory.owner(), _thread(config)
        command = state["messages"][-1].content
        key = command.split(" ", 1)[1]
        if not memory.MEMORY_ID.fullmatch(key) or runtime.store is None:
            raise ValueError("invalid_revoke")
        item = await runtime.store.aget(memory.store_namespace(identity), key)
        if not item or not isinstance(item.value, dict) or item.value.get("owner") != identity:
            raise ValueError("not_active")
        if item.value.get("status") == "revoked":
            return _reply("already_revoked", "案例已撤销；没有重复写入。", revoke_request=None)
        memory.validate_record(item.value, identity, item.value["source"]["thread_id"])
        request = {"memory_id": key, "record_hash": memory.digest(item.value),
                   "owner": identity, "thread_id": thread_id}
        return {"revoke_request": request, "memory_status": "revoke_pending"}
    except (ValueError, PermissionError, TypeError, KeyError):
        return _reply("rejected", "目标记录不存在或不可撤销；没有修改 Memory Store。",
                      revoke_request=None)
    except Exception:  # noqa: BLE001 - store read failure reveals no value
        return _reply("unknown", "Memory Store 查询失败；没有发出撤销写入。",
                      revoke_request=None)


def revoke_review(state: dict, config: RunnableConfig) -> dict:
    request = state.get("revoke_request")
    if state.get("memory_status") != "revoke_pending" or not isinstance(request, dict):
        return _reply("rejected", "撤销审阅状态无效。")
    decision = interrupt({"kind": "incident_memory_revoke_review",
                          "memory_id": request["memory_id"],
                          "record_hash": request["record_hash"],
                          "schema_version": memory.SCHEMA_VERSION,
                          "options": ["approve", "reject"],
                          "notice": "撤销后该历史案例不再可用；Checkpoint 历史不会清除。"})
    try:
        valid = (isinstance(decision, dict) and set(decision) == {
            "kind", "memory_id", "record_hash", "schema_version", "decision"}
            and decision.get("kind") == "incident_memory_revoke_review"
            and decision.get("memory_id") == request["memory_id"]
            and decision.get("record_hash") == request["record_hash"]
            and type(decision.get("schema_version")) is int
            and decision["schema_version"] == memory.SCHEMA_VERSION
            and decision.get("decision") == "approve"
            and request["owner"] == memory.owner()
            and request["thread_id"] == _thread(config))
    except (ValueError, PermissionError, TypeError, KeyError):
        valid = False
    if not valid:
        return _reply("rejected", "撤销审批拒绝或参数无效；记录保持原状。")
    return {"memory_status": "revoke_approved"}


async def revoke_commit(state: dict, config: RunnableConfig, runtime: Runtime) -> dict:
    start = time.monotonic()
    request = state.get("revoke_request")
    key = request.get("memory_id") if isinstance(request, dict) else None
    status = "rejected"
    try:
        identity, thread_id = memory.owner(), _thread(config)
        if (not incident_memory_write_enabled() or state.get("memory_status") != "revoke_approved"
                or request.get("owner") != identity or request.get("thread_id") != thread_id
                or runtime.store is None):
            raise ValueError("invalid_revoke_state")
        status = await memory.revoke(runtime.store, key, request["record_hash"], identity)
    except (ValueError, PermissionError, TypeError, KeyError, AttributeError):
        pass
    _audit("incident_memory_revoke", key, status, start)
    return _reply(status, f"Incident Memory 撤销结果：{status}。")
