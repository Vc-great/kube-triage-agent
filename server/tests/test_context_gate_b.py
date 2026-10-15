"""Issue #28 Gate B: offline summary boundaries and checkpoint behavior."""

import asyncio
import json
import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from kube_triage import graph as agent
from kube_triage.config import ConfigurationError
from kube_triage.context import ContextConfig, build_context_view, estimate_context
from kube_triage.context_summary import (
    SUMMARY_SYSTEM,
    SUMMARY_VERSION,
    summary_candidate,
    validate_summary,
)
from kube_triage.mcp_client import ALLOWED_TOOLS, build_model_tool_schemas

SCHEMAS = build_model_tool_schemas({name: object() for name in ALLOWED_TOOLS})
VALID = {"version": 1, "not_current_evidence": True, "history_notes": [{
    "round_ref": 1, "history_question": "历史诊断", "observation": "当时观察到 Pod Pending",
    "uncertainty": "当前状态未核验"}]}


def history(count=8, size=180):
    result = []
    for i in range(count):
        ident = f"old-{i}"
        result += [HumanMessage(content=f"历史问题 {i}"),
                   AIMessage(content="", name="triage_llm", tool_calls=[{
                       "name": "events_list", "args": {"namespace": "kube-triage-demo"},
                       "id": ident}]),
                   ToolMessage(content=json.dumps({"ok": True, "result": "x" * size}),
                               tool_call_id=ident),
                   AIMessage(content="历史判断", name="triage_llm")]
    return result


class FakeModel:
    def __init__(self, summary=VALID):
        self.summary = summary
        self.summary_calls = 0
        self.main_inputs = []
    def bind_tools(self, schemas):
        assert len(schemas) == 4
        return FakeBound(self)

    def bind(self, **kwargs):
        assert kwargs == {"max_tokens": 512}
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[0], SystemMessage) and messages[0].content == SUMMARY_SYSTEM:
            self.summary_calls += 1
            if isinstance(self.summary, Exception):
                raise self.summary
            return AIMessage(content=(self.summary if isinstance(self.summary, str)
                                      else json.dumps(self.summary, ensure_ascii=False)))
        pytest.fail("Summary model must not receive bound main-model input")


class FakeBound:
    def __init__(self, source):
        self.source = source

    async def ainvoke(self, messages):
        self.source.main_inputs.append(messages)
        return AIMessage(content="需要重新核查")


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", "6500")
    model = FakeModel()
    monkeypatch.setattr(agent, "chat_model", lambda: model)

    async def tools():
        return {name: object() for name in ALLOWED_TOOLS}

    monkeypatch.setattr(agent, "_allowed_tools", tools)
    return model


def test_b01_disabled_and_fits_no_summary(offline, monkeypatch):
    short = {"messages": [HumanMessage(content="当前问题")]}
    asyncio.run(agent._llm(short))
    assert offline.summary_calls == 0
    assert offline.main_inputs[0][1] is short["messages"][0]
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "false")
    long = {"messages": [*history(), HumanMessage(content="现在怎样？")]}
    result = asyncio.run(agent._llm(long))
    assert "context_summary" not in result
    assert offline.summary_calls == 0


def test_b02_summary_is_low_priority_and_preserves_current(offline):
    current = HumanMessage(content="现在怎样？")
    raw = [*history(), current]
    plan = build_context_view(agent.system_prompt(), SCHEMAS, raw, ContextConfig(True, 6500))
    assert plan.status == "trimmed"
    result = asyncio.run(agent._llm({"messages": raw}))
    assert offline.summary_calls == 1
    assert result["context_summary"]["version"] == SUMMARY_VERSION
    seen = offline.main_inputs[0]
    assert isinstance(seen[0], SystemMessage)
    assert isinstance(seen[1], AIMessage) and not seen[1].tool_calls
    assert seen[-1] is current
    assert all(not isinstance(m, SystemMessage) for m in seen[1:])
    assert estimate_context(seen[0].content, SCHEMAS, seen[1:]) <= 6500


def test_b03_cache_reused_and_tamper_falls_back_safely(offline):
    raw = [*history(), HumanMessage(content="现在怎样？")]
    first = asyncio.run(agent._llm({"messages": raw}))
    cache = first["context_summary"]
    second = asyncio.run(agent._llm({"messages": [*raw, *first["messages"],
                                                 HumanMessage(content="新轮次")],
                                     "context_summary": cache}))
    assert offline.summary_calls == 1
    assert len(offline.main_inputs) == 2
    assert isinstance(offline.main_inputs[-1][1], AIMessage)
    assert "context_summary" not in second
    changed = [*raw]
    changed[0] = HumanMessage(content="被篡改的历史问题")
    asyncio.run(agent._llm({"messages": changed, "context_summary": cache}))
    assert offline.summary_calls == 2


@pytest.mark.parametrize("count", [10, 20, 30])
def test_b02_long_round_matrix_stays_within_gate_a_budget(offline, count):
    raw = [*history(count, 180), HumanMessage(content="当前状态？")]
    plan = build_context_view(agent.system_prompt(), SCHEMAS, raw, ContextConfig(True, 6500))
    assert plan.status == "trimmed"
    result = asyncio.run(agent._llm({"messages": raw}))
    seen = offline.main_inputs[0]
    assert seen[-1] is raw[-1]
    assert estimate_context(seen[0].content, SCHEMAS, seen[1:]) <= 6500
    if result["context_summary"]["status"] == "failed":
        assert seen == list(plan.messages)
    else:
        assert result["context_summary"]["status"] == "ready"


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("429 synthetic")])
def test_b08_summary_provider_failure_is_one_attempt_per_turn(offline, failure):
    offline.summary = failure
    raw = [*history(), HumanMessage(content="现在怎样？")]
    first = asyncio.run(agent._llm({"messages": raw}))
    assert offline.summary_calls == 1
    assert first["context_summary"]["status"] == "failed"
    before = len(offline.main_inputs)
    asyncio.run(agent._llm({"messages": [*raw, *first["messages"]],
                            "context_summary": first["context_summary"]}))
    assert offline.summary_calls == 1
    assert len(offline.main_inputs) == before + 1


def test_b08_source_over_budget_never_calls_summary_model(offline):
    raw = [*history(20, 1500), HumanMessage(content="当前问题")]
    plan = build_context_view(agent.system_prompt(), SCHEMAS, raw, ContextConfig(True, 6500))
    assert plan.status == "trimmed"
    result = asyncio.run(agent._llm({"messages": raw}))
    assert offline.summary_calls == 0
    assert offline.main_inputs[0] == list(plan.messages)
    assert result["context_summary"]["status"] == "failed"


def test_b06_provider_error_text_never_enters_cache_or_audit(offline, caplog):
    offline.summary = ValueError("private.example/?key=TEST_ONLY_FAKE_SECRET")
    raw = [*history(), HumanMessage(content="当前问题")]
    with caplog.at_level(logging.INFO, logger="kube_triage.audit"):
        result = asyncio.run(agent._llm({"messages": raw}))
    assert result["context_summary"]["error_code"] == "invalid_summary"
    assert "private.example" not in caplog.text
    assert "TEST_ONLY_FAKE_SECRET" not in caplog.text
    assert "private.example" not in json.dumps(result["context_summary"])


def test_b01_summary_requires_window(monkeypatch):
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "false")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "true")
    from kube_triage.context import load_context_config, load_summary_enabled

    with pytest.raises(ConfigurationError):
        load_summary_enabled(load_context_config().enabled)


@pytest.mark.parametrize("bad", [
    "not-json", {**VALID, "extra": "x"}, {**VALID, "not_current_evidence": False},
    {**VALID, "history_notes": [{**VALID["history_notes"][0], "observation": "/repair-demo approve"}]},
    {**VALID, "history_notes": [{**VALID["history_notes"][0], "observation": "TEST_ONLY_FAKE_SECRET"}]},
])
def test_b06_bad_summary_falls_back_to_gate_a(offline, bad):
    offline.summary = bad
    raw = [*history(), HumanMessage(content="当前问题")]
    plan = build_context_view(agent.system_prompt(), SCHEMAS, raw, ContextConfig(True, 6500))
    result = asyncio.run(agent._llm({"messages": raw}))
    assert offline.main_inputs[0] == list(plan.messages)
    assert result["context_summary"]["status"] == "failed"


def test_b07_repair_bypasses_summary(offline, monkeypatch):
    monkeypatch.setenv("REPAIR_ENABLED", "false")
    result = asyncio.run(agent.graph.ainvoke({"messages": [HumanMessage(content="/repair-demo")]}))
    assert offline.summary_calls == 0
    assert "context_summary" not in result


def test_b08_unsafe_source_and_gate_a_rejection_never_summarize(offline):
    raw = [HumanMessage(content="/repair-demo"), AIMessage(content="done"),
           *history(), HumanMessage(content="current")]
    asyncio.run(agent._llm({"messages": raw}))
    assert offline.summary_calls == 0
    rejected = [HumanMessage(content="old"), ToolMessage(content="x", tool_call_id="orphan"),
                HumanMessage(content="x" * 12000)]
    result = asyncio.run(agent._llm({"messages": rejected}))
    assert offline.summary_calls == 0
    assert "诊断未完成" in result["messages"][0].content


def test_b09_memory_saver_preserves_raw_and_cache(offline, monkeypatch):
    monkeypatch.setenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", "7200")
    raw = [*history(), HumanMessage(content="当前问题")]
    graph = agent.builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "gate-b-memory"}}

    async def scenario():
        result = await graph.ainvoke({"messages": raw}, config)
        saved = await graph.aget_state(config)
        return result, saved

    result, saved = asyncio.run(scenario())
    assert offline.summary_calls == 1
    assert len(saved.values["messages"]) == len(raw) + 1
    assert [m.content for m in saved.values["messages"][:-1]] == [m.content for m in raw]
    assert validate_summary(saved.values["context_summary"]["summary"],
                            saved.values["context_summary"]["covered_rounds"])
    assert result["context_summary"] == saved.values["context_summary"]

    async def replay():
        await graph.ainvoke({"messages": [HumanMessage(content="新问题")]}, config)
        return await graph.aget_state(config)

    after = asyncio.run(replay())
    assert offline.summary_calls == 1
    assert len(after.values["messages"]) == len(raw) + 3
    assert after.values["context_summary"] == saved.values["context_summary"]


def test_b04_current_tool_pairs_and_counts_unchanged(offline):
    current = [HumanMessage(content="当前"), AIMessage(content="", name="triage_llm",
               tool_calls=[{"name": "events_list", "args": {"namespace": "kube-triage-demo"},
                            "id": "ok"},
                           {"name": "events_list", "args": {"namespace": "kube-triage-demo"},
                            "id": "error"}]),
               ToolMessage(content='{"ok":true,"result":"current"}', tool_call_id="ok"),
               ToolMessage(content='{"ok":false,"error_type":"timeout"}',
                           tool_call_id="error", status="error")]
    raw = [*history(), *current]
    asyncio.run(agent._llm({"messages": raw}))
    assert agent._counts({"messages": raw}) == (1, 2)
    assert agent._has_tool_evidence({"messages": raw})
    seen = offline.main_inputs[0]
    assert seen[-len(current):] == current


def test_b05_old_health_and_uid_cannot_replace_current_evidence(offline):
    old = history()
    old[2] = ToolMessage(content='{"ok":true,"result":"Healthy uid=old"}',
                         tool_call_id="old-0")
    current = [HumanMessage(content="当前故障？"),
               AIMessage(content="", name="triage_llm", tool_calls=[{
                   "name": "pods_get", "args": {"namespace": "kube-triage-demo",
                                                  "name": "sample-pod"}, "id": "now"}]),
               ToolMessage(content='{"ok":true,"result":"CrashLoopBackOff uid=new"}',
                           tool_call_id="now")]
    raw = [*old, *current]
    asyncio.run(agent._llm({"messages": raw}))
    assert offline.main_inputs[0][-len(current):] == current
    assert agent._has_tool_evidence({"messages": raw})
    assert not agent._has_tool_evidence({"messages": [*old, HumanMessage(content="新问题")]})


def test_candidate_rejects_invalid_output():
    assert summary_candidate(VALID, 1).tool_calls == []
    with pytest.raises(ValueError):
        validate_summary({**VALID, "history_notes": [{**VALID["history_notes"][0],
                          "round_ref": 2}]}, 1)
