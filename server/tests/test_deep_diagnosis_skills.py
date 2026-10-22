"""复用 #80 正常 FakeModel 契约；V2 不包含旧 pin/攻击恢复矩阵。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

CASES = ["CrashLoopBackOff", "OOMKilled", "ImagePullBackOff", "你好", "healthy",
         "疑似 OOM，证据不足", "ErrImagePull", "频繁重启"]


@pytest.mark.parametrize("scenario", ["progressive", "budgets", "paths", "multiturn",
                                    "forbidden", "not_found", "timeout", "off-on", "p0"])
def test_skills_contract(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(TRIAGE_ENV="test", LANGSMITH_TRACING="false", OTEL_SDK_DISABLED="true",
               APP_HISTORY_ENABLED="false", APP_EVIDENCE_ENABLED="false")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            capture_output=True, text=True, env=env, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["scenario"] == scenario


async def probe(scenario):
    def denied(*args, **kwargs):
        raise AssertionError("本测试禁止网络、真实 Provider 与真实 Reader")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    from deepagents.backends import CompositeBackend
    from deepagents.middleware.skills import SkillsMiddleware, _list_skills
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from pydantic import Field

    from kube_triage import deep_diagnosis_skills as skills
    from kube_triage.deep_diagnosis_skills_fake import SkillsProtocolFakeModel
    from kube_triage.mcp_client import validate_call
    from kube_triage.mock_mcp import events_list, pods_get, pods_list_in_namespace, pods_log

    readers = {"pods_get": pods_get, "pods_list_in_namespace": pods_list_in_namespace,
               "events_list": events_list, "pods_log": pods_log}
    reader_calls = []

    async def mock_reader(name, args, thread_id=None):
        validate_call(name, args)
        reader_calls.append((name, args))
        if scenario in {"forbidden", "not_found", "timeout"}:
            return {"ok": False, "error_type": scenario, "error": "合成 403/404/超时"}
        return {"ok": True, "result": json.dumps(readers[name](**args), ensure_ascii=False)}

    skills.planning.baseline.call_tool = mock_reader

    class Fake(SkillsProtocolFakeModel):
        inputs: list = Field(default_factory=list)
        tools_seen: list = Field(default_factory=list)
        scripted: list | None = None

        def bind_tools(self, tools, **kwargs):
            self.tools_seen.append([t.name for t in tools])
            return self

        def _reply(self, messages):
            self.inputs.append(deepcopy(messages))
            if self.scripted is not None:
                return self.scripted.pop(0)
            return super()._reply(messages)

    def call(name, args, ident):
        return {"name": name, "args": args, "id": ident}

    async def invoke(model, prompt="CrashLoopBackOff", graph=None, config=None):
        graph = graph if graph is not None else skills.build_graph(model)
        return await graph.ainvoke({"messages": [HumanMessage(content=prompt)]}, config)

    if scenario == "p0":
        model = Fake(scripted=[AIMessage(content="你好")])
        await skills.planning.build_graph(model).ainvoke({"messages": [HumanMessage(content="你好")]})
        assert all(set(names) == skills.planning.MODEL_TOOLS for names in model.tools_seen)
        return {"scenario": scenario}
    if scenario in {"progressive", "off-on"}:
        rows = []
        for prompt in CASES:
            for enabled in ([True] if scenario == "progressive" else [False, True]):
                model = Fake()
                if not enabled:
                    # Separate provider profile avoids unioning P0 exclusions
                    # into the Skills profile in this SDK's global registry.
                    from deepagents import (
                        GeneralPurposeSubagentProfile,
                        HarnessProfile,
                        create_deep_agent,
                        register_harness_profile,
                    )
                    from langchain.agents.middleware import TodoListMiddleware

                    register_harness_profile("skills_off", HarnessProfile(
                        excluded_tools=skills.planning.baseline._HIDDEN,
                        excluded_middleware=frozenset({"SummarizationMiddleware"}),
                        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))

                    class OffFake(Fake):
                        def _get_ls_params(self, stop=None, **kwargs):
                            return {"ls_provider": "skills_off", "ls_model_name": "off-fake"}

                    model = OffFake()
                    graph = create_deep_agent(model=model, tools=skills.planning._planning_tools(),
                        middleware=[TodoListMiddleware(), skills.planning.PlanningBoundary()],
                        skills=None, memory=None, subagents=[],
                        system_prompt="只读合成诊断，区分观察、推断与未知。")
                else:
                    graph = skills.build_graph(model)
                start = time.perf_counter()
                result = await invoke(model, prompt, graph)
                elapsed = time.perf_counter() - start
                calls = [c for m in result["messages"] if isinstance(m, AIMessage)
                         for c in m.tool_calls]
                read_calls = [c for c in calls if c["name"] == "read_file"]
                first = str(model.inputs[0])
                if enabled:
                    for name in skills.NAMES:
                        assert name in first
                    for item in _list_skills(CompositeBackend(
                            default=skills.SkillSnapshot(), routes={skills.ROOT: skills.SkillSnapshot()}),
                            skills.ROOT):
                        assert item["description"] in first
                    for heading in ["# CrashLoop 只读诊断", "# OOMKilled 只读诊断", "# ImagePull 只读诊断"]:
                        assert heading not in first
                    expected = ("oom-diagnosis" if "oom" in prompt.lower() else
                                "imagepull-diagnosis" if "imagepull" in prompt.lower() else
                                "crashloop-diagnosis" if "crashloop" in prompt.lower()
                                or "重启" in prompt else None)
                    assert len(read_calls) == (1 if expected else 0)
                    if expected:
                        assert read_calls[0]["args"]["file_path"] == skills.ROOT + expected + "/SKILL.md"
                        assert any("只读诊断" in str(m) for m in model.inputs[1])
                    assert all(set(names) == skills.MODEL_TOOLS and len(names) == 6
                               for names in model.tools_seen)
                else:
                    assert not read_calls and "## 内置诊断 Skills" not in first
                    assert all(set(names) == skills.planning.MODEL_TOOLS for names in model.tools_seen)
                assert not any(m.additional_kwargs.get("lc_source") == "pinned_skill"
                               for m in result["messages"])
                tools = [m for m in result["messages"] if isinstance(m, ToolMessage)]
                assert [c["id"] for c in calls] == [m.tool_call_id for m in tools]
                if prompt != "你好":
                    assert "UNKNOWN" in result["messages"][-1].content
                    assert "skills-pods_get" in result["messages"][-1].content
                rows.append({"case": prompt, "skills": enabled,
                    "selected": [c["args"]["file_path"] for c in read_calls],
                    "tool_calls": len(calls), "seconds": round(elapsed, 4),
                    "input_chars": sum(len(str(m)) for request in model.inputs for m in request),
                    "provider_tokens": "NOT RUN"})
        assert SkillsMiddleware.abefore_agent is skills.ReadOnlySkillsMiddleware.abefore_agent
        return {"scenario": scenario, "rows": rows}
    if scenario == "multiturn":
        model, saver = Fake(), MemorySaver()
        graph = skills.build_graph(model, checkpointer=saver)
        config = {"configurable": {"thread_id": "v2-normal-history"}}
        first = await invoke(model, graph=graph, config=config)
        assert "UNKNOWN" in first["messages"][-1].content
        # Rebuild to simulate reopening an ordinary completed Thread.
        reopened = skills.build_graph(model, checkpointer=saver)
        second = await invoke(model, "上轮结论是什么", reopened, config)
        assert "UID=" in second["messages"][-1].content
        third = await invoke(model, "OOMKilled", reopened, config)
        calls = [c for m in third["messages"] if isinstance(m, AIMessage) for c in m.tool_calls]
        assert sum(c["name"] == "read_file" for c in calls) == 2
        assert len((await reopened.aget_state(config)).values["skills_metadata"]) == 3
    elif scenario in {"forbidden", "not_found", "timeout"}:
        result = await invoke(Fake(), "诊断 Pod crashloop-pod CrashLoopBackOff")
        assert "未核验" in result["messages"][-1].content
        assert any(isinstance(m, ToolMessage) and m.status == "error" for m in result["messages"])
    elif scenario in {"paths", "budgets"}:
        paths = [skills.ROOT + "crashloop-diagnosis/SKILL.md"] * 3 if scenario == "budgets" else [
            skills.ROOT + "crashloop-diagnosis/SKILL.md", "/unavailable/SKILL.md"]
        model = Fake(scripted=[
            AIMessage(content="", tool_calls=[call("read_file", {"file_path": path}, f"read-{i}")
                                             for i, path in enumerate(paths)]),
            AIMessage(content="", tool_calls=[call("events_list", {"namespace": "kube-triage-demo"},
                                                  f"reader-{i}") for i in range(7)]),
            AIMessage(content="UNKNOWN；预算用尽，调查未完成。"),
        ])
        result = await invoke(model)
        replies = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert sum(m.name == "read_file" and m.status == "success" for m in replies) == (
            2 if scenario == "budgets" else 1)
        assert len(reader_calls) == 6
        assert replies[-1].status == "error"
        snapshot = skills.SkillSnapshot()
        assert len(snapshot.hashes) == 3
        assert snapshot.read("/unavailable").error
        assert len(_list_skills(CompositeBackend(
            default=snapshot, routes={skills.ROOT: snapshot}), skills.ROOT)) == 3
    return {"scenario": scenario}


if __name__ == "__main__":
    os.environ["TRIAGE_MOCK_DATASET"] = "memory-web"
    print(json.dumps(asyncio.run(probe(sys.argv[1])), ensure_ascii=False))
