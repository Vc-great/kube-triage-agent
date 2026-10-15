"""正式产品 Graph + 真实模型；仅四个 Reader 的传输改为冻结合成回执。"""

import json
import logging
import os
from pathlib import Path
from typing import ClassVar

from kube_triage import graph as product
from kube_triage import incident_memory_retrieval, mcp_client, prompts
from langgraph.config import get_config

_cases = {row["case_id"]: row for row in json.loads(
    Path(os.environ["PHASE34_CASES_PATH"]).read_text(encoding="utf-8"))["cases"]}
FIXED_PROMPT = prompts.SYSTEM_PROMPT + prompts.MEMORY_READ_POLICY


class _PrivateAudit(logging.Handler):
    """只记录审计白名单字段和 Thread ID；不保存提示词或端点。"""

    FIELDS: ClassVar[set[str]] = {
        "event", "status", "estimated_tokens", "omitted_rounds", "error_code",
        "cache_hit", "summary_calls", "input_tokens", "output_tokens",
        "duration_ms", "hit_count", "candidate_count", "candidate_truncated",
        "injected", "comparison", "budget", "latency_ms"}

    def emit(self, record):
        try:
            value = json.loads(record.getMessage())
            if not isinstance(value, dict) or value.get("event") not in {
                    "context_view", "context_summary", "incident_memory_context",
                    "incident_memory_retrieve"}:
                return
            try:
                thread = get_config().get("configurable", {}).get("thread_id")
            except RuntimeError:
                thread = None
            item = {key: value[key] for key in self.FIELDS if key in value}
            item.update(thread_id=thread, batch=os.getenv("PHASE34_BATCH", "unknown"))
            path = os.environ["PHASE34_AUDIT_PATH"]
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (json.dumps(item, ensure_ascii=False) + "\n").encode())
            finally:
                os.close(fd)
        except (OSError, TypeError, ValueError, KeyError):
            self.handleError(record)


_audit_logger = logging.getLogger("kube_triage.audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.addHandler(_PrivateAudit())


async def mock_tools():
    return {name: object() for name in mcp_client.ALLOWED_TOOLS}


async def mock_reader(name, args, thread_id=None):
    mcp_client.validate_call(name, args)
    if name not in mcp_client.ALLOWED_TOOLS:
        raise AssertionError("仅允许四个 Reader")
    mapping = json.loads(Path(os.environ["PHASE34_THREAD_MAP"]).read_text(encoding="utf-8"))
    spec = mapping.get(thread_id)
    if not isinstance(spec, dict) or spec.get("case_id") not in _cases:
        return {"ok": False, "error": "unknown_synthetic_thread", "error_type": "mock"}
    case = _cases[spec["case_id"]]
    if args.get("namespace") != case["namespace"]:
        return {"ok": False, "error": "wrong_synthetic_namespace", "error_type": "mock"}
    if name in {"pods_get", "pods_log"} and args.get("name") != case["target_pod"]:
        return {"ok": False, "error": "unmapped_synthetic_target", "error_type": "mock"}
    # pods_log 的合法 tail/container 只选择截取方式，不改变冻结的合成日志。
    return case["reader_responses"][name]


async def forbidden_repair(*_args, **_kwargs):
    raise AssertionError("Phase 3-4 禁止 Repair transport")


_original_retrieve = incident_memory_retrieval.retrieve_incidents
_original_summary = product.generate_summary


class _StoreTimeout:
    def __init__(self, real_store):
        self.real_store = real_store

    async def asearch(self, *_args, **_kwargs):
        raise TimeoutError("synthetic_store_asearch_timeout")


async def retrieve_with_fault(store, owner, prompt, **kwargs):
    # 仅 fault-v1 的 P34-10 注入 Store API 边界错误；Checkpointer 仍可用。
    if os.getenv("PHASE34_BATCH") in {"fault-v1", "fault-v2"}:
        target = incident_memory_retrieval.target_pod(prompt)
        if target == "p34-10-target":
            store = _StoreTimeout(store)
    return await _original_retrieve(store, owner, prompt, **kwargs)


async def summary_with_fault(model, rounds):
    # fault-v1 的 P34-08 只在摘要 Provider 边界注入超时，不影响诊断模型调用。
    if os.getenv("PHASE34_BATCH") in {"fault-v1", "fault-v2"}:
        try:
            thread = get_config().get("configurable", {}).get("thread_id")
        except RuntimeError:
            thread = None
        mapping = json.loads(Path(os.environ["PHASE34_THREAD_MAP"]).read_text(encoding="utf-8"))
        if isinstance(mapping.get(thread), dict) and mapping[thread].get("case_id") == "P34-08":
            raise TimeoutError("synthetic_summary_timeout")
    return await _original_summary(model, rounds)


product._allowed_tools = mock_tools
product.call_tool = mock_reader
product.system_prompt = lambda: FIXED_PROMPT
product.repair.read_scale = forbidden_repair
product.repair.write_scale_once = forbidden_repair
product.repair.pod_readiness = forbidden_repair
incident_memory_retrieval.retrieve_incidents = retrieve_with_fault
product.generate_summary = summary_with_fault
graph = product.graph
