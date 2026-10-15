"""隔离 setup 专用：正式 Graph + FakeModel/历史 Mock Reader 的脚本审批种子。"""

import json
import os
from pathlib import Path
from uuid import uuid4

from kube_triage import graph as product
from kube_triage import mcp_client
from langchain_core.messages import AIMessage, ToolMessage

CASES = {case["case_id"]: case for case in json.loads(
    Path(os.environ["PHASE33_CASES_PATH"]).read_text(encoding="utf-8"))["cases"]}


class SeedModel:
    def bind_tools(self, schemas):
        assert {item["function"]["name"] for item in schemas} == mcp_client.ALLOWED_TOOLS
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="合成历史 Pod 症状；根因未核验。")
        for message in reversed(messages):
            if getattr(message, "type", None) == "human":
                name = str(message.content).split("Pod ")[-1].strip()
                break
        else:
            raise AssertionError("missing synthetic target")
        return AIMessage(content="", tool_calls=[{"id": uuid4().hex,
            "name": "pods_get", "args": {"namespace": mcp_client.NAMESPACE, "name": name}}])


async def mock_tools():
    return {name: object() for name in mcp_client.ALLOWED_TOOLS}


async def historical_reader(name, args, thread_id=None):
    mcp_client.validate_call(name, args)
    if name != "pods_get":
        raise AssertionError("setup 仅需 pods_get")
    mapping = json.loads(Path(os.environ["PHASE33_THREAD_MAP"]).read_text(encoding="utf-8"))
    spec = mapping.get(thread_id)
    if not isinstance(spec, dict):
        raise TypeError("unknown seed thread")
    case = CASES[spec["case_id"]]
    history = case["historical_records"]["relevant" if spec["arm"] == "B" else "distractor"][spec["index"]]
    if args["name"] != case["target_pod"]:
        raise AssertionError("wrong synthetic target")
    symptom = history["symptom"]
    status = {"phase": "Running" if symptom in {"CrashLoopBackOff", "ImagePullBackOff"} else symptom}
    if symptom in {"CrashLoopBackOff", "ImagePullBackOff"}:
        status["containerStatuses"] = [{"state": {"waiting": {"reason": symptom}}}]
    pod = {"kind": "Pod", "metadata": {"namespace": mcp_client.NAMESPACE,
                                     "name": args["name"], "uid": history["observed_uid"]},
           "status": status}
    return {"ok": True, "result": json.dumps(pod)}


async def forbidden_repair(*_args, **_kwargs):
    raise AssertionError("Phase 3-3 禁止 Repair transport")


product.chat_model = SeedModel
product._allowed_tools = mock_tools
product.call_tool = historical_reader
product.repair.read_scale = forbidden_repair
product.repair.write_scale_once = forbidden_repair
product.repair.pod_readiness = forbidden_repair
graph = product.graph
