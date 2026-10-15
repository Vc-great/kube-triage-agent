"""Phase 3-3 冻结设计与隔离 fixture 的离线门禁。"""

import importlib.util
import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from kube_triage import graph as agent
from kube_triage import incident_memory_retrieval as retrieval

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_cases_trigger_exact_target_and_map_readers():
    evaluation = _load("scripts/eval_incident_memory_real.py")
    cases = evaluation.cases()
    assert len(cases) == 12
    for case in cases:
        assert retrieval.target_pod(case["user_prompt"]) == case["target_pod"]
        key = json.dumps({"name": "pods_get", "args": {
            "namespace": "kube-triage-demo", "name": case["target_pod"]}},
            sort_keys=True, ensure_ascii=False)
        assert key in case["mock_tool_responses"]
        assert case["historical_records"]["relevant"]
        assert case["historical_records"]["distractor"]


def test_pair_plan_has_frozen_balanced_denominator():
    evaluation = _load("scripts/eval_incident_memory_real.py")
    pilot = evaluation.make_plan("pilot")
    formal = evaluation.make_plan("formal")
    assert pilot["planned_runs"] == 18
    assert formal["planned_runs"] == 180
    assert len({pair["pair_id"] for pair in formal["pairs"]}) == 60
    assert all(sorted(pair["arm_order"]) == ["A", "B", "C"]
               for pair in formal["pairs"])
    assert len({tuple(pair["arm_order"]) for pair in formal["pairs"]}) > 1


def test_judge_requires_complete_typed_schema():
    import pytest

    judge = _load("scripts/eval_incident_memory_judge.py")
    valid = {key: False for key in judge.FIELDS}
    valid["reason"] = "独立证据不足。"
    assert judge.validate(valid) == valid
    with pytest.raises(ValueError):
        judge.validate({**valid, "diagnosis_correct": "false"})
    with pytest.raises(ValueError):
        judge.validate({key: value for key, value in valid.items() if key != "reason"})
    assert judge.uid_relations("current-04", [
        {"observed_uid": "current-04"}, {"observed_uid": "stale-04"},
        {"observed_uid": None}]) == ["same", "new", "unknown"]


def test_abnormal_oom_pod_shape_is_not_silently_rewritten():
    evaluation = _load("scripts/eval_incident_memory_real.py")
    case = next(row for row in evaluation.cases() if row["case_id"] == "P33-06")
    key = json.dumps({"name": "pods_get", "args": {
        "namespace": "kube-triage-demo", "name": "p33-06"}}, sort_keys=True)
    pod = json.loads(case["mock_tool_responses"][key]["result"])
    assert pod["status"]["containerStatuses"][0]["lastState"]["terminated"]["reason"] == "OOMKilled"
    assert pod["status"]["containerStatuses"][0]["state"]["waiting"]["reason"] == "CrashLoopBackOff"


def test_reader_attestation_survives_a_second_tool_batch(monkeypatch):
    """真实先导复现：第二轮 events_list 曾清空首次 pods_get 的 HMAC。"""
    import asyncio

    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "synthetic-provenance-secret-0123456789")
    monkeypatch.setenv("DEMO_API_TOKEN", "synthetic-demo-token-separate-0123456789")

    class TwoBatchModel:
        def bind_tools(self, schemas):
            assert len(schemas) == 4
            return self

        async def ainvoke(self, messages):
            tool_count = sum(isinstance(msg, ToolMessage) for msg in messages)
            if tool_count == 0:
                return AIMessage(content="", tool_calls=[{"id": "first-pod-call",
                    "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "p33-01"}}])
            if tool_count == 1:
                return AIMessage(content="", tool_calls=[{"id": "second-event-call",
                    "name": "events_list", "args": {"namespace": "kube-triage-demo"}}])
            return AIMessage(content="当前 Pod CrashLoopBackOff，根因未确定。")

    async def fake_tools():
        return {name: object() for name in
                ("pods_get", "pods_log", "events_list", "pods_list_in_namespace")}

    async def fake_reader(name, _args, _thread_id=None):
        if name == "events_list":
            return {"ok": True, "result": "[]"}
        pod = {"kind": "Pod", "metadata": {"namespace": "kube-triage-demo",
                                          "name": "p33-01", "uid": "current-01"},
               "status": {"phase": "Running", "containerStatuses": [
                   {"state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}
        return {"ok": True, "result": json.dumps(pod)}

    monkeypatch.setattr(agent, "chat_model", TwoBatchModel)
    monkeypatch.setattr(agent, "_allowed_tools", fake_tools)
    monkeypatch.setattr(agent, "call_tool", fake_reader)
    graph = agent.builder.compile(checkpointer=MemorySaver())

    async def scenario():
        state = await graph.ainvoke({"messages": [HumanMessage(content="诊断 Pod p33-01")]},
                                    {"configurable": {"thread_id": "two-batch-thread"}})
        assert [msg.name for msg in state["messages"] if isinstance(msg, ToolMessage)] == [
            "pods_get", "events_list"]
        assert len(state["reader_attestations"]) == 1
        assert retrieval.current_pod_evidence(state["messages"], state["reader_attestations"],
                                              "two-batch-thread", "p33-01")[0] == "verified"

    asyncio.run(scenario())
