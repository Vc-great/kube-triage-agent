"""Offline policy and checkpoint tests. Every scale write here is simulated."""

import asyncio
from pathlib import Path

import pytest
import yaml
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from kube_triage import graph as agent
from kube_triage import repair

ROOT = Path(__file__).resolve().parents[2]


def demo_deployment(uid="demo-uid"):
    data = yaml.safe_load((ROOT / "infra/k8s/repair-demo.yaml").read_text())
    data["metadata"]["uid"] = uid
    return data


def test_repair_command_is_exact_and_disabled(monkeypatch):
    assert agent._route({"messages": [HumanMessage(content="/repair-demo")]}) == "repair_prepare"
    assert agent._route({"messages": [HumanMessage(content="/repair-demo other")]}) != "repair_prepare"
    monkeypatch.delenv("REPAIR_ENABLED", raising=False)

    async def forbidden():
        pytest.fail("disabled flow must not query the Repairer")

    monkeypatch.setattr(repair, "read_deployment", forbidden)
    result = asyncio.run(agent._repair_prepare({"messages": []}))
    assert result["repair_status"] == "denied"


def test_fixed_scale_args_and_target_validation():
    assert repair._scale_args(1) == {"apiVersion": "apps/v1", "kind": "Deployment",
                                     "name": repair.NAME, "namespace": repair.NAMESPACE, "scale": 1}
    for value in (0, 2, True):
        with pytest.raises(ValueError):
            repair._scale_args(value)
    wrong = demo_deployment()
    wrong["metadata"]["labels"][repair.LABEL] = "other-project"
    with pytest.raises(ValueError):
        repair.validate_deployment(wrong)


def test_repair_manifest_is_namespaced_and_minimal():
    docs = list(yaml.safe_load_all((ROOT / "infra/k8s/repair-rbac.yaml").read_text()))
    assert [doc["kind"] for doc in docs] == ["ServiceAccount", "Role", "RoleBinding"]
    role = docs[1]
    assert role["metadata"]["namespace"] == repair.NAMESPACE
    assert role["rules"] == [
        {"apiGroups": ["apps"], "resources": ["deployments/scale"],
         "resourceNames": [repair.NAME], "verbs": ["get", "update"]},
        {"apiGroups": ["apps"], "resources": ["deployments"],
         "resourceNames": [repair.NAME], "verbs": ["get"]},
    ]
    assert docs[2]["roleRef"]["name"] == role["metadata"]["name"]


def test_simulated_deployment_matches_real_policy(monkeypatch):
    monkeypatch.setenv("REPAIR_SIMULATED", "true")

    async def scale():
        return {"replicas": 0, "uid": "simulated-demo-uid"}

    monkeypatch.setattr(repair, "read_scale", scale)
    data = asyncio.run(repair.read_deployment())
    assert repair.validate_deployment(data) == "simulated-demo-uid"


@pytest.mark.parametrize("decision,expected_writes", [
    ({"decision": "reject"}, 0),
    ({"decision": "approve", "proposal_id": "wrong"}, 0),
    ({"decision": "other"}, 0),
    ({"decision": "approve", "namespace": "default"}, 0),
    ({"decision": "approve", "kind": "StatefulSet"}, 0),
    ({"decision": "approve", "name": "other"}, 0),
    ({"decision": "approve", "target_replicas": 2}, 0),
    ({"decision": "approve"}, 1),
])
def test_checkpoint_approval_and_single_write(monkeypatch, decision, expected_writes):
    monkeypatch.setenv("REPAIR_ENABLED", "true")
    replicas = [0]
    writes = []

    async def get_deployment():
        data = demo_deployment()
        data["spec"]["replicas"] = replicas[0]
        return data

    async def get_scale():
        return {"replicas": replicas[0], "uid": "demo-uid"}

    async def write():
        writes.append(repair._scale_args(1))
        replicas[0] = 1

    async def ready(_thread_id):
        return "ready"

    monkeypatch.setattr(repair, "read_deployment", get_deployment)
    monkeypatch.setattr(repair, "read_scale", get_scale)
    monkeypatch.setattr(repair, "write_scale_once", write)
    monkeypatch.setattr(repair, "pod_readiness", ready)
    graph = agent.builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "test-thread"}}

    async def scenario():
        first = await graph.ainvoke({"messages": [HumanMessage(content="/repair-demo")]}, config)
        proposal = first["repair_proposal"]
        assert first["repair_status"] == "pending" and proposal["proposal_id"]
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("repair_approval",)
        assert snapshot.values["repair_proposal"]["proposal_id"] == proposal["proposal_id"]
        resume = {"decision": decision["decision"],
                  "proposal_id": decision.get("proposal_id", proposal["proposal_id"])}
        for key in ("namespace", "kind", "name", "target_replicas"):
            if key in decision:
                resume[key] = decision[key]
        final = await graph.ainvoke(Command(resume=resume), config)
        return final

    final = asyncio.run(scenario())
    assert len(writes) == expected_writes
    if expected_writes:
        assert final["repair_result"]["classification"] == "写操作已成功且可验证"
        assert writes == [repair._scale_args(1)]
    else:
        assert final["repair_status"] == "rejected"


def test_recheck_prevents_repeat_or_changed_target(monkeypatch):
    monkeypatch.setenv("REPAIR_ENABLED", "true")
    writes = []

    async def deployment():
        data = demo_deployment()
        data["spec"]["replicas"] = 1
        return data

    async def scale_one():
        return {"replicas": 1, "uid": "demo-uid"}

    async def write():
        writes.append(1)

    async def ready(_thread_id):
        return "ready"

    monkeypatch.setattr(repair, "read_deployment", deployment)
    monkeypatch.setattr(repair, "read_scale", scale_one)
    monkeypatch.setattr(repair, "write_scale_once", write)
    monkeypatch.setattr(repair, "pod_readiness", ready)
    proposal = {"proposal_id": "p", "apiVersion": "apps/v1", "namespace": repair.NAMESPACE,
                "kind": "Deployment", "name": repair.NAME, "uid": "demo-uid",
                "before_replicas": 0, "target_replicas": 1, "source": "explicit-user-command",
                "simulated": False}
    state = {"messages": [], "repair_status": "approved", "repair_proposal": proposal}
    result = asyncio.run(agent._repair_execute(state, {"configurable": {"thread_id": "t"}}))
    assert result["repair_result"]["write_attempted"] is False
    assert writes == []
    proposal["namespace"] = "default"
    result = asyncio.run(agent._repair_execute(state, {"configurable": {"thread_id": "t"}}))
    assert result["repair_status"] == "denied"
    assert writes == []


@pytest.mark.parametrize("error", [ConnectionError("offline"), TimeoutError("timeout"),
                                    PermissionError("403 forbidden"),
                                    PermissionError("401 unauthorized")])
def test_preflight_failures_never_write(monkeypatch, error):
    monkeypatch.setenv("REPAIR_ENABLED", "true")

    async def failed_read():
        raise error

    async def forbidden_write():
        pytest.fail("preflight failure must not write")

    monkeypatch.setattr(repair, "read_deployment", failed_read)
    monkeypatch.setattr(repair, "write_scale_once", forbidden_write)
    result = asyncio.run(agent._repair_prepare({"messages": []}))
    assert result["repair_status"] == "denied"


@pytest.mark.parametrize("replicas", [2, 3, -1])
def test_unexpected_replicas_never_write(monkeypatch, replicas):
    monkeypatch.setenv("REPAIR_ENABLED", "true")

    async def deployment():
        data = demo_deployment()
        data["spec"]["replicas"] = replicas
        return data

    async def scale():
        return {"replicas": replicas, "uid": "demo-uid"}

    async def forbidden():
        pytest.fail("unexpected replica count must never write")

    monkeypatch.setattr(repair, "read_deployment", deployment)
    monkeypatch.setattr(repair, "read_scale", scale)
    monkeypatch.setattr(repair, "write_scale_once", forbidden)
    proposal = {"proposal_id": "p", "apiVersion": "apps/v1", "namespace": repair.NAMESPACE,
                "kind": "Deployment", "name": repair.NAME, "uid": "demo-uid",
                "before_replicas": 0, "target_replicas": 1, "source": "explicit-user-command",
                "simulated": False}
    result = asyncio.run(agent._repair_execute({"messages": [], "repair_status": "approved",
                                                "repair_proposal": proposal},
                                               {"configurable": {"thread_id": "t"}}))
    assert result["repair_result"]["write_attempted"] is False


def test_lost_write_response_is_not_retried_or_claimed_success(monkeypatch):
    monkeypatch.setenv("REPAIR_ENABLED", "true")
    replicas = [0]
    calls = []

    async def deployment():
        data = demo_deployment()
        data["spec"]["replicas"] = replicas[0]
        return data

    async def scale():
        return {"replicas": replicas[0], "uid": "demo-uid"}

    async def lost_ack():
        calls.append(1)
        replicas[0] = 1
        raise TimeoutError("simulated response loss")

    async def ready(_thread_id):
        return "ready"

    monkeypatch.setattr(repair, "read_deployment", deployment)
    monkeypatch.setattr(repair, "read_scale", scale)
    monkeypatch.setattr(repair, "write_scale_once", lost_ack)
    monkeypatch.setattr(repair, "pod_readiness", ready)
    proposal = {"proposal_id": "p", "apiVersion": "apps/v1", "namespace": repair.NAMESPACE,
                "kind": "Deployment", "name": repair.NAME, "uid": "demo-uid",
                "before_replicas": 0, "target_replicas": 1, "source": "explicit-user-command",
                "simulated": False}
    state = {"messages": [], "repair_status": "approved", "repair_proposal": proposal}
    config = {"configurable": {"thread_id": "t"}}
    first = asyncio.run(agent._repair_execute(state, config))["repair_result"]
    second = asyncio.run(agent._repair_execute(state, config))["repair_result"]
    assert calls == [1]
    assert first["classification"] == "写结果未知/失败"
    assert second["write_attempted"] is False
