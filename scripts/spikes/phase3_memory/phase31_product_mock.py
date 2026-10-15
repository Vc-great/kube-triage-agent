"""Phase 3-1 isolated Aegra harness: the *product* builder with fake I/O.

Never deploy this config. It patches every model, Reader and Repair transport
before exporting the product graph; no Kubernetes, MCP or LLM endpoint is used.
"""

import json
from uuid import uuid4

from kube_triage import graph as product
from kube_triage import mcp_client, repair
from langchain_core.messages import AIMessage, ToolMessage

_replicas = 0


class FakeModel:
    def bind_tools(self, schemas):
        assert {item["function"]["name"] for item in schemas} == mcp_client.ALLOWED_TOOLS
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="合成 Pod 当时 CrashLoopBackOff；根因尚未确定。")
        return AIMessage(content="", tool_calls=[{
            "id": uuid4().hex, "name": "pods_get",
            "args": {"namespace": mcp_client.NAMESPACE, "name": "sample-a"},
        }])


async def fake_tools():
    return {name: object() for name in mcp_client.ALLOWED_TOOLS}


async def fake_reader(name, args, _thread_id=None):
    mcp_client.validate_call(name, args)
    if name != "pods_get":
        raise AssertionError("Unexpected Reader call")
    pod = {"kind": "Pod", "metadata": {"namespace": mcp_client.NAMESPACE,
                                       "name": "sample-a", "uid": "synthetic-uid-31"},
           "status": {"phase": "Running", "containerStatuses": [
               {"state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}
    return {"ok": True, "result": json.dumps(pod)}


async def fake_scale():
    return {"replicas": _replicas, "uid": "synthetic-repair-uid-31"}


async def fake_write_scale_once():
    global _replicas
    if _replicas != 0:
        raise AssertionError("Unexpected duplicate fake scale")
    _replicas = 1


async def fake_readiness(_thread_id):
    return "ready"


product.chat_model = FakeModel
product._allowed_tools = fake_tools
product.call_tool = fake_reader
repair.read_scale = fake_scale
repair.write_scale_once = fake_write_scale_once
repair.pod_readiness = fake_readiness
graph = product.graph
