"""隔离评测入口：正式 Graph 和真实 chat_model，只有 Reader I/O 被合成数据替换。"""

import json
import os
from pathlib import Path

from kube_triage import graph as product
from kube_triage import mcp_client

_cases = {case["case_id"]: case for case in json.loads(
    Path(os.environ["PHASE33_CASES_PATH"]).read_text(encoding="utf-8"))["cases"]}


async def mock_tools():
    return {name: object() for name in mcp_client.ALLOWED_TOOLS}


async def mock_reader(name, args, thread_id=None):
    mcp_client.validate_call(name, args)
    if name not in mcp_client.ALLOWED_TOOLS:
        raise AssertionError("仅允许四个 Reader")
    mapping = json.loads(Path(os.environ["PHASE33_THREAD_MAP"]).read_text(encoding="utf-8"))
    case_id = mapping.get(thread_id)
    if case_id not in _cases:
        return {"ok": False, "error": "unknown_synthetic_thread", "error_type": "mock"}
    case = _cases[case_id]
    key = json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
    response = case["mock_tool_responses"].get(key)
    if response is None and name == "pods_log":
        # tail/container only select how the fixed synthetic log is requested.
        # Every valid option returns the same frozen case log, including tail=30.
        canonical = json.dumps({"name": name, "args": {
            "namespace": args["namespace"], "name": args["name"]}},
            sort_keys=True, ensure_ascii=False)
        response = case["mock_tool_responses"].get(canonical)
    if response is None:
        return {"ok": False, "error": "unmapped_synthetic_call", "error_type": "mock"}
    return response


product._allowed_tools = mock_tools
product.call_tool = mock_reader

# Repair is disabled by config. In case a test accidentally reaches its transport,
# fail before any external endpoint can be contacted.
async def forbidden_repair(*_args, **_kwargs):
    raise AssertionError("Phase 3-3 禁止 Repair transport")


product.repair.read_scale = forbidden_repair
product.repair.write_scale_once = forbidden_repair
product.repair.pod_readiness = forbidden_repair
graph = product.graph
