"""Read-only diagnosis plus one explicit, approval-gated scale exercise."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Literal, NotRequired
from uuid import uuid4

import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from kube_triage import incident_memory as memory
from kube_triage import incident_memory_flow as memory_flow
from kube_triage import incident_memory_retrieval as memory_retrieval
from kube_triage import repair
from kube_triage.agent_progress import emit_progress, reset_progress_budget
from kube_triage.app_storage import reader_context
from kube_triage.config import (
    ConfigurationError,
    incident_memory_http_write_blocked,
    incident_memory_max_candidates,
    incident_memory_max_hits,
    incident_memory_read_enabled,
)
from kube_triage.context import (
    ContextPlan,
    _split_safe_rounds,
    build_context_view,
    estimate_context,
    load_context_config,
    load_summary_enabled,
)
from kube_triage.context_summary import (
    SUMMARY_VERSION,
    generate_summary,
    source_fingerprint,
    source_messages,
    summary_candidate,
    validate_summary,
)
from kube_triage.llm import chat_model
from kube_triage.mcp_client import (
    MCP_TIMEOUT_SECONDS,
    NAMESPACE,
    _allowed_tools,
    build_model_tool_schemas,
    call_tool,
)
from kube_triage.prompts import system_prompt

MAX_TOOL_CALLS = 6
MAX_MODEL_DECISIONS = 4
audit = logging.getLogger("kube_triage.audit")


class AgentState(MessagesState):
    context_summary: NotRequired[dict]
    repair_proposal: NotRequired[dict | None]
    repair_status: NotRequired[str]
    repair_result: NotRequired[dict | None]
    memory_candidate: NotRequired[dict | None]
    memory_hash: NotRequired[str | None]
    memory_record: NotRequired[dict | None]
    memory_status: NotRequired[str]
    revoke_request: NotRequired[dict | None]
    reader_attestations: NotRequired[list[dict]]
    memory_references: NotRequired[list[dict]]
    memory_retrieval_status: NotRequired[str]
    memory_target: NotRequired[str | None]


def _current_turn(state: MessagesState) -> list:
    messages = state["messages"]
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _counts(state: MessagesState) -> tuple[int, int]:
    turn = _current_turn(state)
    decisions = sum(isinstance(m, AIMessage) and m.name == "triage_llm" for m in turn)
    calls = sum(isinstance(m, ToolMessage) for m in turn)
    return decisions, calls


def _has_verified_target_evidence(state: AgentState, target: str,
                                  thread_id: str | None = None) -> bool:
    """仅接受与本轮目标配对的 pods_get；启用 Memory 守卫时还需 HMAC。"""
    if incident_memory_http_write_blocked():
        return (isinstance(thread_id, str) and
                memory_retrieval.current_pod_evidence(
                    state["messages"], state.get("reader_attestations"),
                    thread_id, target)[0] == "verified")
    calls = {}
    for message in _current_turn(state):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("name") == "pods_get" and call.get("args") == {
                        "namespace": NAMESPACE, "name": target}:
                    calls[call.get("id")] = True
        elif isinstance(message, ToolMessage) and message.tool_call_id in calls:
            try:
                if message.name != "pods_get" or message.status != "success":
                    continue
                envelope = json.loads(message.content)
                if not isinstance(envelope, dict) or envelope.get("ok") is not True:
                    continue
                result = envelope.get("result")
                if not isinstance(result, str) or not result or len(result) > 16384:
                    continue
                pod = yaml.safe_load(result)
                meta = pod.get("metadata") if isinstance(pod, dict) else None
                if (pod.get("kind") == "Pod" and isinstance(meta, dict)
                        and meta.get("namespace") == NAMESPACE
                        and meta.get("name") == target
                        and isinstance(meta.get("uid"), str)
                        and memory.SAFE_UID.fullmatch(meta["uid"])
                        and isinstance(pod.get("status"), dict)):
                    return True
            except (ValueError, TypeError, yaml.YAMLError):
                continue
    return False


def _target_reader_failure(state: AgentState, target: str) -> str:
    """从配对目标调用的固定错误类型生成安全回执，不引用无关工具数据。"""
    target_ids = {call.get("id") for message in _current_turn(state)
                  if isinstance(message, AIMessage) for call in message.tool_calls
                  if call.get("name") == "pods_get" and call.get("args") == {
                      "namespace": NAMESPACE, "name": target}}
    for message in reversed(_current_turn(state)):
        if isinstance(message, ToolMessage) and message.tool_call_id in target_ids:
            try:
                payload = json.loads(message.content)
            except (TypeError, ValueError):
                break
            if isinstance(payload, dict) and payload.get("ok") is False:
                if payload.get("error_type") == "not_found":
                    return "本轮 Reader 未找到目标 Pod（404）；当前状态与根因未核验。"
                if payload.get("error_type") == "permission":
                    return "本轮 Reader 读取目标 Pod 被拒绝（403）；当前状态与根因未核验。"
            break
    return "本轮没有取得可信的目标 Pod Reader 证据；当前状态与根因未核验。"


def _last_user_text(state: MessagesState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            if isinstance(message.content, str):
                return message.content
            if isinstance(message.content, list):
                return " ".join(
                    part if isinstance(part, str) else str(part.get("text", ""))
                    for part in message.content
                    if isinstance(part, (str, dict))
                )
            return str(message.content)
    return ""


def _route(state: MessagesState) -> Literal[
        "llm", "memory_retrieve", "repair_prepare", "memory_prepare", "revoke_prepare"]:
    command = _last_user_text(state)
    if command.strip() == "/repair-demo":
        return "repair_prepare"
    if command == "/remember-incident":
        return "memory_prepare"
    if re.fullmatch(r"/forget-incident [0-9a-f]{32}", command):
        return "revoke_prepare"
    return "memory_retrieve" if incident_memory_read_enabled() else "llm"


async def _memory_retrieve(state: AgentState, runtime: Runtime) -> dict:
    """Once per ordinary turn; a new turn always replaces old checkpoint refs."""
    try:
        result = await memory_retrieval.retrieve_incidents(
            runtime.store, memory.owner(), _last_user_text(state),
            max_hits=incident_memory_max_hits(),
            max_candidates=incident_memory_max_candidates())
    except (PermissionError, ValueError):
        result = {"references": [], "target": None, "status": "memory_unavailable"}
    return {"memory_references": result["references"],
            "memory_target": result["target"],
            "memory_retrieval_status": result["status"]}


async def _execute_tool(state: AgentState, config: RunnableConfig) -> dict:
    reset_progress_budget()
    ai_message = state["messages"][-1]
    calls = ai_message.tool_calls
    thread_id = config.get("configurable", {}).get("thread_id")
    used = _counts(state)[1]
    attest = incident_memory_http_write_blocked()
    attestations = [] if used == 0 else list(state.get("reader_attestations") or [])
    human = _current_turn(state)[0] if attest else None
    results = []
    for call in calls:
        if used >= MAX_TOOL_CALLS:
            emit_progress("tool", "skipped", tool_name=call["name"], tool_call_id=call["id"])
            response = {"ok": False, "error": "本轮工具调用预算已用尽（6 次）。",
                        "error_type": "budget"}
        else:
            emit_progress("tool", "started", tool_name=call["name"], tool_call_id=call["id"])
            try:
                with reader_context(graph_id="agent", tool_call_id=call["id"],
                                    run_id=config.get("configurable", {}).get("run_id")):
                    response = await call_tool(call["name"], call["args"], thread_id)
            except Exception:
                emit_progress("tool", "failed", tool_name=call["name"], tool_call_id=call["id"])
                raise
            emit_progress("tool", "completed" if response["ok"] else "failed",
                          tool_name=call["name"], tool_call_id=call["id"])
            used += 1
        tool_message = ToolMessage(
            content=json.dumps(response, ensure_ascii=False),
            name=call["name"], tool_call_id=call["id"],
            status="success" if response["ok"] else "error",
            **({"id": uuid4().hex} if attest else {}),
        )
        results.append(tool_message)
        if attest and response["ok"] and call["name"] == "pods_get":
            attestations.append(memory.make_attestation(
                human, ai_message, call, tool_message, thread_id))
    if attest:
        return {"messages": results, "reader_attestations": attestations[-6:]}
    return {"messages": results}


async def _summary_view(model: object, state: AgentState, schemas: list[dict],
                        plan: ContextPlan, total_budget: int) -> tuple[list, dict]:
    """Try one bounded historical summary; otherwise retain Gate A's safe view."""
    rounds = _split_safe_rounds(state["messages"])
    if rounds is None or plan.omitted_rounds < 1:
        return list(plan.messages), {}
    # Keep the most recent completed round and current round intact. A Gate A
    # view usually fills its budget, so a summary needs additional room.
    covered = max(plan.omitted_rounds, len(rounds) - 2)
    prefix = [message for turn in rounds[:covered] for message in turn]
    source_hash = source_fingerprint(prefix)
    turn_hash = source_fingerprint([rounds[-1][0]])
    cache = state.get("context_summary")
    failure_codes = {"empty_source", "unsafe_source", "source_over_budget", "invalid_json",
                     "invalid_schema", "invalid_round_ref", "unsafe_summary",
                     "summary_too_long", "invalid_summary_reply", "final_over_budget",
                     "invalid_summary", "timeout", "rate_limit", "provider_error"}

    def candidate(summary: dict, count: int) -> list | None:
        retained = [message for turn in rounds[count:] for message in turn]
        view = [plan.messages[0], summary_candidate(summary, count), *retained]
        if estimate_context(view[0].content, schemas, view[1:]) <= total_budget:
            return view
        return None

    if (isinstance(cache, dict) and type(cache.get("version")) is int and
            cache.get("version") == SUMMARY_VERSION):
        old_count = cache.get("covered_rounds")
        if isinstance(old_count, int) and not isinstance(old_count, bool) and 0 < old_count < len(rounds):
            old_prefix = [message for turn in rounds[:old_count] for message in turn]
            if cache.get("source_sha256") == source_fingerprint(old_prefix):
                if cache.get("status") == "ready" and set(cache) == {
                        "version", "status", "covered_rounds", "source_sha256",
                        "turn_sha256", "summary"}:
                    try:
                        source_messages(rounds[:old_count])
                        summary = validate_summary(cache.get("summary"), old_count)
                        view = candidate(summary, old_count)
                        if view is not None:
                            emit_progress("context", "cache_hit", context_operation="summary")
                            audit.info(json.dumps({"event": "context_summary", "status": "cache_hit",
                                                   "cache_hit": True, "summary_calls": 0,
                                                   "input_tokens": None, "output_tokens": None,
                                                   "duration_ms": 0, "error_code": None}))
                            return view, {}
                    except ValueError:
                        pass
                if (cache.get("status") == "failed" and set(cache) == {
                        "version", "status", "covered_rounds", "source_sha256",
                        "turn_sha256", "error_code"} and old_count == covered and
                        cache.get("turn_sha256") == turn_hash and
                        isinstance(cache.get("error_code"), str) and
                        cache.get("error_code") in failure_codes):
                    audit.info(json.dumps({"event": "context_summary", "status": "skipped_failed",
                                           "cache_hit": False, "summary_calls": 0,
                                           "input_tokens": None, "output_tokens": None,
                                           "duration_ms": 0, "error_code": cache["error_code"]}))
                    emit_progress("context", "skipped", context_operation="summary")
                    return list(plan.messages), {}

    start = time.monotonic()
    status = "adopted"
    error_code = None
    called = False
    usage = {"input_tokens": None, "output_tokens": None}
    update = {"version": SUMMARY_VERSION, "status": "failed", "covered_rounds": covered,
              "source_sha256": source_hash, "turn_sha256": turn_hash}
    try:
        # Generate only from complete, contiguous omitted rounds. No tool binding.
        source_messages(rounds[:covered])
        called = True
        emit_progress("context", "started", context_operation="summary")
        summary, usage = await generate_summary(model, rounds[:covered])
        view = candidate(summary, covered)
        if view is None:
            raise ValueError("final_over_budget")
        update.update({"status": "ready", "summary": summary})
        emit_progress("context", "completed", context_operation="summary")
        return view, {"context_summary": update}
    except ValueError as exc:
        status = "fallback"
        error_code = str(exc) if str(exc) in failure_codes else "invalid_summary"
    except TimeoutError:
        status, error_code = "fallback", "timeout"
    except Exception as exc:  # noqa: BLE001 - provider errors never expose their text
        name = type(exc).__name__.lower()
        error_code = ("rate_limit" if "ratelimit" in name or "429" in str(exc)
                      else "provider_error")
        status = "fallback"
    finally:
        audit.info(json.dumps({"event": "context_summary", "status": status,
                               "cache_hit": False, "summary_calls": int(called),
                               "input_tokens": usage["input_tokens"],
                               "output_tokens": usage["output_tokens"],
                               "duration_ms": round((time.monotonic() - start) * 1000),
                               "error_code": error_code}, ensure_ascii=False))
    update["error_code"] = error_code
    emit_progress("context", "fallback", context_operation="summary")
    return list(plan.messages), {"context_summary": update}


async def _llm(state: AgentState) -> dict:
    reset_progress_budget()
    decisions, _used = _counts(state)
    if decisions >= MAX_MODEL_DECISIONS:
        return {"messages": [AIMessage(content=(
            "已达到本轮模型决策上限（4 轮）。请根据上方证据人工核查；"
            "若证据不足，不能断言根因。"))]}
    model = chat_model()  # Configuration errors fail the Run, never become a healthy answer.
    summary_update: dict = {}
    try:
        native_tools = await asyncio.wait_for(_allowed_tools(), MCP_TIMEOUT_SECONDS)
        schemas = build_model_tool_schemas(native_tools)
        context_config = load_context_config()
        summary_enabled = load_summary_enabled(context_config.enabled)
        prompt = system_prompt()
        plan = build_context_view(prompt, schemas, state["messages"], context_config)
        audit.info(json.dumps({"event": "context_view", "status": plan.status,
                               "estimated_tokens": plan.estimated_tokens,
                               "omitted_rounds": plan.omitted_rounds,
                               "error_code": plan.error_code}, ensure_ascii=False))
        if not plan.ok:
            emit_progress("context", "failed", context_operation="trim")
            return {"messages": [AIMessage(content=(
                "估算上下文超预算或历史轮次无法安全裁剪；本次诊断未完成。"
                "请使用新 Thread 或缩小输入。"))]}
        view = list(plan.messages)
        if plan.status == "trimmed":
            emit_progress("context", "completed", context_operation="trim")
        if summary_enabled and plan.status == "trimmed":
            view, summary_update = await _summary_view(
                model, state, schemas, plan, context_config.total_budget)
        injected_refs = []
        if incident_memory_read_enabled() and state.get("memory_references"):
            target = state.get("memory_target")
            try:
                thread_id = get_config().get("configurable", {}).get("thread_id")
            except RuntimeError:
                thread_id = None
            if (isinstance(target, str) and isinstance(thread_id, str)
                    and memory.SAFE_ID.fullmatch(thread_id)):
                evidence = memory_retrieval.current_pod_evidence(
                    state["messages"], state.get("reader_attestations"), thread_id, target)
                compared = memory_retrieval.compare_references(
                    state["memory_references"], evidence)
                # Preserve all Gate A/B messages and tool pairs. The reference
                # is a separate assistant data slot before the current Human.
                budget = min(context_config.total_budget, 16384)
                view, injected_refs = memory_retrieval.bounded_memory_view(
                    view, schemas, compared, budget)
                audit.info(json.dumps({"event": "incident_memory_context",
                                       "injected": len(injected_refs),
                                       "comparison": evidence[0],
                                       "budget": budget}, ensure_ascii=False))
        model = model.bind_tools(schemas)
        emit_progress("model", "started")
        reply = await model.ainvoke(view)
        if not isinstance(reply, AIMessage):
            raise TypeError("LLM returned a non-AI message")
        if reply.invalid_tool_calls:
            return {**summary_update, "messages": [AIMessage(content=(
                "模型返回了无法解析的 Tool Call；请确认模型服务支持标准 Tool Calling。"))]}
        if not reply.tool_calls and not reply.content:
            return {**summary_update, "messages": [AIMessage(content=(
                "模型未返回内容或标准 Tool Call；本次诊断未完成。"))]}
        if not reply.tool_calls:
            target = memory_retrieval.target_pod(_last_user_text(state))
            if target:
                try:
                    thread_id = get_config().get("configurable", {}).get("thread_id")
                except RuntimeError:
                    thread_id = None
                if not _has_verified_target_evidence(state, target, thread_id):
                    safe = _target_reader_failure(state, target)
                    if injected_refs:
                        safe += memory_retrieval.display_references(injected_refs)
                    return {**summary_update, "messages": [AIMessage(content=safe)]}
        if not reply.tool_calls and injected_refs and evidence[0] != "verified":
            return {**summary_update, "messages": [AIMessage(content=(
                "本轮未取得可信的目标 Pod Reader 证据；当前状态和根因未核验。"
                + memory_retrieval.display_references(injected_refs)))]}
        reply.name = "triage_llm"
        if not reply.tool_calls and injected_refs:
            reply.content = str(reply.content) + memory_retrieval.display_references(injected_refs)
        emit_progress("model", "completed")
        if not reply.tool_calls:
            emit_progress("answer", "completed")
        return {**summary_update, "messages": [reply]}
    except ConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider/MCP errors vary by SDK
        emit_progress("model", "failed")
        name = type(exc).__name__.lower()
        if "ratelimit" in name or "429" in str(exc):
            detail = "模型请求被限流（429）"
        elif ("contextlength" in name or "context_length" in name or
              any(marker in str(exc).lower() for marker in (
                  "context length", "context window", "context_length_exceeded",
                  "maximum context", "too many tokens", "input is too long"))):
            detail = "Provider 实际 Context Limit 超限"
        elif "timeout" in name:
            detail = "模型请求超时"
        elif "connect" in name or isinstance(exc, OSError):
            detail = "模型或 MCP 连接失败"
        else:
            detail = "模型调用或 MCP 工具发现失败"
        return {**summary_update, "messages": [AIMessage(content=f"{detail}；本次诊断未完成。")]}


def _after_llm(state: MessagesState) -> Literal["tools", "__end__"]:
    return "tools" if state["messages"][-1].tool_calls else END


def _repair_stop(message: str, status: str = "denied") -> dict:
    return {"repair_proposal": None, "repair_status": status, "repair_result": None,
            "messages": [AIMessage(content=message)]}


async def _repair_prepare(_state: AgentState) -> dict:
    if not repair.repair_enabled():
        return _repair_stop("受控恢复功能未启用（REPAIR_ENABLED=false）；没有执行 Kubernetes 写入。")
    try:
        deployment = await repair.read_deployment()
        uid = repair.validate_deployment(deployment)
        scale = await repair.read_scale()
        if (scale["uid"] != uid or scale["replicas"] != 0 or
                deployment["spec"].get("replicas") != 0):
            return _repair_stop("目标 UID 或初始副本数不符；只允许从 0 提案恢复到 1。")
    except Exception as exc:  # noqa: BLE001 - fail closed for any upstream format/transport error
        return _repair_stop(f"预检失败（{repair.safe_error(exc)}）；没有生成审批或执行写入。")
    proposal = {"proposal_id": uuid4().hex, "apiVersion": repair.API_VERSION,
                "namespace": repair.NAMESPACE, "kind": repair.KIND, "name": repair.NAME,
                "uid": uid, "before_replicas": 0, "target_replicas": 1,
                "impact": "只把本项目演示 Deployment 从 0 副本扩到 1；Pod Ready 需另行验证。",
                "source": "explicit-user-command", "simulated": repair.simulated()}
    return {"repair_proposal": proposal, "repair_status": "pending", "repair_result": None,
            "messages": [AIMessage(content="已核实固定演示资源当前为 0 副本。请在下方审阅提案。") ]}


def _after_repair_prepare(state: AgentState) -> Literal["repair_approval", "__end__"]:
    return "repair_approval" if state.get("repair_status") == "pending" else END


def _repair_approval(state: AgentState, config: RunnableConfig) -> dict:
    proposal = state.get("repair_proposal")
    if not proposal or state.get("repair_status") != "pending":
        return _repair_stop("审批状态缺失；拒绝执行。")
    decision = interrupt({"kind": "repair_approval", "proposal": proposal,
        "question": "是否批准把 kube-triage-demo/Deployment/triage-repair-demo 从 0 扩到 1？",
        "options": ["approve", "reject"]})
    valid = (isinstance(decision, dict) and set(decision) == {"decision", "proposal_id"}
             and decision.get("proposal_id") == proposal["proposal_id"])
    approved = valid and decision["decision"] == "approve"
    thread_id = config.get("configurable", {}).get("thread_id")
    audit.info(json.dumps({"event": "repair_decision", "thread_id": thread_id,
        "proposal_id": proposal["proposal_id"], "namespace": repair.NAMESPACE,
        "name": repair.NAME, "decision": "approve" if approved else "reject_or_invalid"},
        ensure_ascii=False))
    if not approved:
        return {"repair_status": "rejected", "messages": [AIMessage(content=(
            "审批拒绝或 proposal_id/参数无效；没有执行 Kubernetes 写入。"))]}
    return {"repair_status": "approved", "messages": [AIMessage(content=(
        "审批已通过；执行节点将重新检查目标与副本数。"))]}


def _after_repair_approval(state: AgentState) -> Literal["repair_execute", "__end__"]:
    return "repair_execute" if state.get("repair_status") == "approved" else END


async def _repair_execute(state: AgentState, config: RunnableConfig) -> dict:
    start = time.monotonic()
    proposal = state.get("repair_proposal") or {}
    thread_id = config.get("configurable", {}).get("thread_id")
    fixed = {"apiVersion": repair.API_VERSION, "namespace": repair.NAMESPACE,
             "kind": repair.KIND, "name": repair.NAME, "before_replicas": 0,
             "target_replicas": 1, "source": "explicit-user-command"}
    if (not repair.repair_enabled() or state.get("repair_status") != "approved" or
            not proposal.get("proposal_id") or not proposal.get("uid") or
            proposal.get("simulated") != repair.simulated() or
            any(proposal.get(key) != value for key, value in fixed.items())):
        return _repair_stop("执行前安全状态校验失败；没有执行 Kubernetes 写入。")
    write_attempted = False
    write_reply = False
    classification = "写结果未知/失败"
    detail = ""
    pod_status = "unknown"
    observed = None
    try:
        deployment = await repair.read_deployment()
        repair.validate_deployment(deployment, proposal["uid"])
        before = await repair.read_scale()
        if (before["uid"] != proposal["uid"] or
                deployment["spec"].get("replicas") != before["replicas"]):
            raise ValueError("Scale UID changed")
        if before["replicas"] == 0:
            write_attempted = True
            try:
                await repair.write_scale_once()
                write_reply = True
            except Exception as exc:  # noqa: BLE001 - response loss may follow a committed update
                detail = f"写请求回执未知（{repair.safe_error(exc)}）；已停止重试并尝试只读回查。"
        elif before["replicas"] == 1:
            detail = "已达到目标副本数；未再次写入（no-op）。"
        else:
            raise ValueError("Pre-execution replicas is neither 0 nor 1")
        try:
            after = await repair.read_scale()
            if after["uid"] != proposal["uid"]:
                raise ValueError("Scale UID changed during verification")
            observed = after["replicas"]
            if observed == 1:
                pod_status = await repair.pod_readiness(thread_id)
                if write_attempted and not write_reply:
                    classification = "写结果未知/失败"
                    detail += " 回查为 1，但不能证明本次请求是唯一写入来源。"
                elif pod_status == "ready":
                    classification = "写操作已成功且可验证" if write_attempted else "目标已达成（无重复写入）"
                elif pod_status.startswith("unknown"):
                    classification = ("写请求已回执且 scale=1；Pod Ready 未知" if write_attempted
                                      else "目标已达成；Pod Ready 未知")
                else:
                    classification = "写请求提交但 Pod 尚未 Ready" if write_attempted else "目标已达成但 Pod 尚未 Ready"
            else:
                detail += f" 回查副本数为 {observed}，目标未达成。"
        except Exception as exc:  # noqa: BLE001 - verification failure stays uncertain
            detail += f" 回查失败（{repair.safe_error(exc)}）。"
    except Exception as exc:  # noqa: BLE001 - fail closed before any write
        detail = f"执行前检查失败（{repair.safe_error(exc)}）；没有发出写请求。"
    result = {"classification": classification, "write_attempted": write_attempted,
              "write_response_received": write_reply, "observed_replicas": observed,
              "pod_ready": pod_status, "detail": detail, "simulated": repair.simulated()}
    audit.info(json.dumps({"event": "repair_result", "thread_id": thread_id,
        "proposal_id": proposal["proposal_id"], "namespace": repair.NAMESPACE,
        "name": repair.NAME, "classification": classification,
        "write_attempted": write_attempted,
        "duration_ms": round((time.monotonic() - start) * 1000)}, ensure_ascii=False))
    return {"repair_status": "finished", "repair_result": result,
            "messages": [AIMessage(content=(f"{'离线模拟；' if repair.simulated() else ''}"
                                         f"{classification}。scale={observed}；Pod Ready：{pod_status}。"
                                         f"{detail} 0→1 只是演示，不代表故障根因已修复。"))]}


builder = StateGraph(AgentState)
builder.add_node("llm", _llm)
builder.add_node("memory_retrieve", _memory_retrieve)
builder.add_node("tools", _execute_tool)
builder.add_node("repair_prepare", _repair_prepare)
builder.add_node("repair_approval", _repair_approval)
builder.add_node("repair_execute", _repair_execute)
builder.add_node("memory_prepare", memory_flow.prepare)
builder.add_node("memory_review", memory_flow.review)
builder.add_node("memory_commit", memory_flow.commit)
builder.add_node("revoke_prepare", memory_flow.revoke_prepare)
builder.add_node("revoke_review", memory_flow.revoke_review)
builder.add_node("revoke_commit", memory_flow.revoke_commit)
builder.add_conditional_edges(START, _route)
builder.add_edge("memory_retrieve", "llm")
builder.add_conditional_edges("llm", _after_llm)
builder.add_edge("tools", "llm")
builder.add_conditional_edges("repair_prepare", _after_repair_prepare)
builder.add_conditional_edges("repair_approval", _after_repair_approval)
builder.add_edge("repair_execute", END)
builder.add_conditional_edges("memory_prepare", lambda s: "memory_review" if
                              s.get("memory_status") == "pending" else END)
builder.add_conditional_edges("memory_review", lambda s: "memory_commit" if
                              s.get("memory_status") == "approved" else END)
builder.add_edge("memory_commit", END)
builder.add_conditional_edges("revoke_prepare", lambda s: "revoke_review" if
                              s.get("memory_status") == "revoke_pending" else END)
builder.add_conditional_edges("revoke_review", lambda s: "revoke_commit" if
                              s.get("memory_status") == "revoke_approved" else END)
builder.add_edge("revoke_commit", END)
graph = builder.compile()
