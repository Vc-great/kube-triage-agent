"""历史准备专用 FakeModel；正式诊断必须切换 phase34_real_model_mock。"""

import json
import os
from pathlib import Path
from uuid import uuid4

from kube_triage import graph as product
from kube_triage import mcp_client
from langchain_core.messages import AIMessage, ToolMessage

CASES = {row["case_id"]: row for row in json.loads(
    Path(os.environ["PHASE34_CASES_PATH"]).read_text(encoding="utf-8"))["cases"]}


class SeedModel:
    def bind_tools(self, schemas):
        assert {item["function"]["name"] for item in schemas} == mcp_client.ALLOWED_TOOLS
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            # 合成旧时间说明只用于历史构造，不计入正式模型收益。
            envelope = json.loads(messages[-1].content)
            pod = json.loads(envelope["result"])
            status = pod["status"]
            containers = status.get("containerStatuses") or []
            waiting = (containers[0].get("state", {}).get("waiting", {}) if containers else {})
            symptom = waiting.get("reason", status["phase"])
            ready = any(item.get("type") == "Ready" and item.get("status") == "True"
                        for item in status.get("conditions") or [])
            fact = (f"2026-09-01 的旧时间合成记录：UID={pod['metadata']['uid']}，"
                    f"症状={symptom}，Ready={ready}。该状态仅属于历史；"
                    "新问题必须重新读取当前 Pod，根因未核验。")
            return AIMessage(content=fact * 12)
        human = next(message for message in reversed(messages)
                     if getattr(message, "type", None) == "human")
        target = str(human.content).split("Pod ")[-1].strip()
        return AIMessage(content="", tool_calls=[{"id": uuid4().hex,
            "name": "pods_get", "args": {"namespace": mcp_client.NAMESPACE, "name": target}}])


async def mock_tools():
    return {name: object() for name in mcp_client.ALLOWED_TOOLS}


async def historical_reader(name, args, thread_id=None):
    mcp_client.validate_call(name, args)
    if name != "pods_get":
        raise AssertionError("历史准备只允许 pods_get")
    mapping = json.loads(Path(os.environ["PHASE34_THREAD_MAP"]).read_text(encoding="utf-8"))
    spec = mapping.get(thread_id)
    if not isinstance(spec, dict):
        raise TypeError("未知的合成历史 Thread")
    case = CASES[spec["case_id"]]
    if args["name"] != case["target_pod"]:
        raise AssertionError("历史准备读取了错误 Pod")
    history = (case["memory_seeds"][spec.get("index", 0)] if spec.get("kind") == "memory"
               else case["historical_conversation"])
    symptom = history.get("symptom", history.get("old_symptom"))
    uid = history.get("observed_uid", history.get("old_uid"))
    status = {"phase": "Running" if symptom in {"CrashLoopBackOff", "ImagePullBackOff"} else symptom,
              "conditions": [{"type": "Ready", "status": "False"}],
              "containerStatuses": [{"state": {"waiting": {"reason": symptom}}}]
              if symptom in {"CrashLoopBackOff", "ImagePullBackOff"} else []}
    pod = {"kind": "Pod", "metadata": {"namespace": mcp_client.NAMESPACE,
                                     "name": args["name"], "uid": uid}, "status": status}
    return {"ok": True, "result": json.dumps(pod, ensure_ascii=False)}


async def forbidden_repair(*_args, **_kwargs):
    raise AssertionError("Phase 3-4 历史准备禁止 Repair transport")


product.chat_model = SeedModel
product._allowed_tools = mock_tools
product.call_tool = historical_reader
product.repair.read_scale = forbidden_repair
product.repair.write_scale_once = forbidden_repair
product.repair.pod_readiness = forbidden_repair
graph = product.graph
