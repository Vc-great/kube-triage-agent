"""Phase 3-4：成功回执必须属于本轮目标 Pod。"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from kube_triage import graph


def test_wrong_pod_success_is_not_verified_target(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "synthetic-phase34-hmac-secret-0123456789")
    monkeypatch.setenv("DEMO_API_TOKEN", "synthetic-phase34-api-token-0123456789")
    human = HumanMessage(content="诊断 Pod p34-09-target")
    call = {"id": "wrong-target-call", "name": "pods_get",
            "args": {"namespace": "kube-triage-demo", "name": "p34-09-target"}}
    ai = AIMessage(content="", tool_calls=[call])
    other = {"kind": "Pod", "metadata": {"namespace": "kube-triage-demo",
                                        "name": "p34-09-other", "uid": "other34-09"},
             "status": {"phase": "Running"}}
    tool = ToolMessage(content=json.dumps({"ok": True, "result": json.dumps(other)}),
                       name="pods_get", tool_call_id=call["id"], status="success")
    state = {"messages": [human, ai, tool]}
    assert graph._has_tool_evidence(state) is True  # 原问题：任意成功回执被当作可用证据。
    assert graph._has_verified_target_evidence(state, "p34-09-target") is False


def test_unrelated_success_does_not_verify_failed_target(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "true")
    human = HumanMessage(content="诊断 Pod p34-07-target")
    ai = AIMessage(content="", tool_calls=[
        {"id": "failed-target", "name": "pods_get",
         "args": {"namespace": "kube-triage-demo", "name": "p34-07-target"}},
        {"id": "unrelated-success", "name": "events_list",
         "args": {"namespace": "kube-triage-demo"}}])
    failed = ToolMessage(content=json.dumps({"ok": False, "error_type": "permission",
                                             "error": "403 synthetic"}),
                         name="pods_get", tool_call_id="failed-target", status="error")
    unrelated = ToolMessage(content=json.dumps({"ok": True, "result": "[]"}),
                            name="events_list", tool_call_id="unrelated-success",
                            status="success")
    state = {"messages": [human, ai, failed, unrelated]}
    assert graph._has_tool_evidence(state) is True
    assert graph._has_verified_target_evidence(state, "p34-07-target") is False


@pytest.mark.parametrize("mode", ["403", "wrong_pod"])
def test_graph_overrides_model_claim_without_target_proof(monkeypatch, mode):
    import asyncio

    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "synthetic-phase34-hmac-secret-0123456789")
    monkeypatch.setenv("DEMO_API_TOKEN", "synthetic-phase34-api-token-0123456789")
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", "9000")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "false")
    target = "p34-07-target" if mode == "403" else "p34-09-target"

    class OverclaimModel:
        def bind_tools(self, _schemas):
            return self

        async def ainvoke(self, messages):
            if any(isinstance(item, ToolMessage) for item in messages):
                return AIMessage(content="目标 Pod 已核验，当前健康，根因是数据库。")
            return AIMessage(content="", tool_calls=[
                {"id": "target-call", "name": "pods_get",
                 "args": {"namespace": "kube-triage-demo", "name": target}},
                {"id": "unrelated-call", "name": "events_list",
                 "args": {"namespace": "kube-triage-demo"}}])

    async def fake_tools():
        return {name: object() for name in
                ("pods_get", "pods_log", "events_list", "pods_list_in_namespace")}

    async def fake_reader(name, _args, _thread_id=None):
        if name == "events_list":
            return {"ok": True, "result": "[]"}
        if mode == "403":
            return {"ok": False, "error_type": "permission", "error": "403 synthetic"}
        other = {"kind": "Pod", "metadata": {"namespace": "kube-triage-demo",
                                            "name": "p34-09-other", "uid": "other34-09"},
                 "status": {"phase": "Running"}}
        return {"ok": True, "result": json.dumps(other)}

    monkeypatch.setattr(graph, "chat_model", OverclaimModel)
    monkeypatch.setattr(graph, "_allowed_tools", fake_tools)
    monkeypatch.setattr(graph, "call_tool", fake_reader)
    compiled = graph.builder.compile(checkpointer=MemorySaver())
    state = asyncio.run(compiled.ainvoke(
        {"messages": [HumanMessage(content=f"诊断 Pod {target}")]},
        {"configurable": {"thread_id": f"phase34-{mode}"}}))
    answer = state["messages"][-1].content
    assert "已核验" not in answer
    assert "根因是数据库" not in answer
    assert "未核验" in answer
    if mode == "403":
        assert "403" in answer
