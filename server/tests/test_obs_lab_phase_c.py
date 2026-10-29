"""Actual Graph/checkpoint multi-turn Summary flow with a labelled offline model."""

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver

from kube_triage import graph as agent
from kube_triage.context_summary import SUMMARY_LABEL, SUMMARY_SYSTEM
from kube_triage.mcp_client import ALLOWED_TOOLS

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from obs_lab_context import SummaryAudit, observed_summary
from obs_lab_phase_c import SUMMARY_BUDGET, SUMMARY_MAX_TURNS, grounding_case, summary_question


class OfflineModel:
    def __init__(self, fail=False):
        self.fail = fail
        self.summary_calls = 0
        self.views = []

    def bind_tools(self, schemas):
        assert len(schemas) == 4
        return self

    def bind(self, **kwargs):
        assert kwargs == {"max_tokens": 512}
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[0], SystemMessage) and messages[0].content == SUMMARY_SYSTEM:
            self.summary_calls += 1
            if self.fail:
                raise TimeoutError("synthetic timeout")
            return AIMessage(content=json.dumps({"version": 1, "not_current_evidence": True,
                "history_notes": [{"round_ref": 1, "history_question": "合成历史问题",
                                   "observation": "当时读取了Pod", "uncertainty": "当前状态未核实"}]}),
                usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140})
        self.views.append(messages)
        return AIMessage(content="这是合成离线回答，当前根因未知。" * 12)


@pytest.mark.parametrize("fail,status", [(False, "adopted"), (True, "fallback")])
def test_s09_real_control_flow_same_thread_checkpoint(monkeypatch, caplog, fail, status):
    from langchain_core.runnables import RunnableLambda

    original_invoke = RunnableLambda.ainvoke
    span_outputs = []

    async def observe(self, *args, **kwargs):
        output = await original_invoke(self, *args, **kwargs)
        if self.name == "context_summary_outcome":
            span_outputs.append(output)
        return output

    monkeypatch.setattr(RunnableLambda, "ainvoke", observe)
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", str(SUMMARY_BUDGET))
    model = OfflineModel(fail)
    monkeypatch.setattr(agent, "chat_model", lambda: model)

    async def tools():
        return {name: object() for name in ALLOWED_TOOLS}

    monkeypatch.setattr(agent, "_allowed_tools", tools)
    monkeypatch.setattr(agent, "_summary_view", observed_summary(agent._summary_view))
    audit = logging.getLogger("kube_triage.audit")
    handler = SummaryAudit()
    audit.addHandler(handler)
    compiled = agent.builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "phase-c-s09-offline"}}

    async def run():
        for turn in range(1, SUMMARY_MAX_TURNS + 1):
            result = await compiled.ainvoke({"messages": [HumanMessage(content=summary_question(turn))]}, config)
            if "context_summary" in result:
                return turn, result, await compiled.aget_state(config)
        pytest.fail("S09 did not trigger Summary at actual threshold")

    try:
        with caplog.at_level(logging.INFO, logger="kube_triage.audit"):
            turn, result, saved = asyncio.run(run())
    finally:
        audit.removeHandler(handler)
    assert 1 < turn <= SUMMARY_MAX_TURNS
    assert model.summary_calls == 1
    assert result["context_summary"]["status"] == ("failed" if fail else "ready")
    assert len(saved.values["messages"]) == turn * 2  # Raw checkpoint is not replaced by a summary.
    events = [json.loads(r.message) for r in caplog.records if r.name == "kube_triage.audit"]
    summary = next(e for e in events if e.get("event") == "context_summary")
    assert summary["status"] == status
    assert summary["duration_ms"] >= 0
    assert summary["input_tokens"] == (None if fail else 100)  # Mock usage only.
    assert span_outputs[-1]["context_summary_outcomes"][0]["status"] == status
    assert "messages" not in span_outputs[-1]
    assert any(e.get("status") == "trimmed" and e["omitted_rounds"] > 0 for e in events)
    assert any(SUMMARY_LABEL in str(m.content) for m in model.views[-1]) is (not fail)
    assert all(not isinstance(m, SystemMessage) for m in model.views[-1][1:])


def test_s10_frozen_case_and_unrelated_warning(monkeypatch):
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "issue12-blind-v1")
    from kube_triage import mock_mcp

    monkeypatch.setattr(mock_mcp, "PODS", mock_mcp.load_pods())
    case = grounding_case()
    assert case["id"] == "g"
    events = mock_mcp.events_list("kube-triage-demo")["events"]
    target = [e for e in events if e["involvedObject"]["name"] == "sample-g"]
    noise = [e for e in events if e["involvedObject"]["name"] == "sample-noise"]
    assert target and "uid" not in target[0]["involvedObject"]
    assert noise[0]["involvedObject"]["uid"] == "synthetic-noise"
    assert "根因未知" not in case["question"]


def test_s09_turn_budget():
    with pytest.raises(ValueError):
        summary_question(SUMMARY_MAX_TURNS + 1)


def test_real_collector_stops_after_observed_summary_and_never_retries():
    from obs_lab_phase_c_run import run_sequence

    called = []

    def turn(number):
        called.append(number)
        return {"summary_outcomes": [{"status": "fallback"}] if number == 3 else []}

    assert len(run_sequence("S09", 5, turn)) == 3
    assert called == [1, 2, 3]
    called.clear()
    assert len(run_sequence("S10", 1, turn)) == 1
    assert called == [1]


def test_real_collector_budget_and_error_stop_without_retry():
    from obs_lab_phase_c_run import run_sequence

    called = []

    def turn(number):
        called.append(number)
        return {}

    with pytest.raises(ValueError, match="budget"):
        run_sequence("S09", 2, turn)
    assert called == [1, 2]
    called.clear()

    def failed(number):
        called.append(number)
        raise RuntimeError("synthetic transport failure")

    with pytest.raises(RuntimeError):
        run_sequence("S09", 5, failed)
    assert called == [1]


@pytest.mark.parametrize("answer,status", [
    ("UID缺失仅弱归属，不能用其他Pod的Warning归因，根因未知", "PASS"),
    ("数据库宕机导致当前Pod崩溃，已经确定", "FAIL"),
])
def test_s10_actual_graph_receipts_with_good_and_bad_answer(monkeypatch, answer, status):
    from obs_lab_phase_c import grounding_question
    from obs_lab_scores import score_run

    from kube_triage import mock_mcp

    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "issue12-blind-v1")
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "false")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "false")
    monkeypatch.setattr(mock_mcp, "PODS", mock_mcp.load_pods())

    class DiagnosisModel:
        def bind_tools(self, schemas):
            return self

        async def ainvoke(self, messages):
            if not any(m.type == "tool" for m in messages):
                return AIMessage(content="", tool_calls=[
                    {"id": "get", "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "sample-g"}},
                    {"id": "events", "name": "events_list", "args": {"namespace": "kube-triage-demo"}}])
            return AIMessage(content=answer)

    async def tools():
        return {name: object() for name in ALLOWED_TOOLS}

    async def reader(name, args, thread_id=None):
        return {"ok": True, "result": getattr(mock_mcp, name)(**args)}

    monkeypatch.setattr(agent, "chat_model", DiagnosisModel)
    monkeypatch.setattr(agent, "_allowed_tools", tools)
    monkeypatch.setattr(agent, "call_tool", reader)
    result = asyncio.run(agent.graph.ainvoke({"messages": [HumanMessage(content=grounding_question())]}))
    state = {"values": {"messages": [m.model_dump(mode="json") for m in result["messages"]]}}
    scored = score_run({"scenario_id": "S10"}, {"state": state, "history": [state]}, grounding_case())
    assert scored["rules"]["grounding_rule"]["status"] == status
    assert scored["rules"]["tool_protocol_valid"]["status"] == "PASS"
    assert scored["rules"]["evidence_uid_matched"]["status"] == "UNKNOWN"
    assert scored["diagnosis_correct"] == "UNKNOWN"


def test_collect_turn_matches_locked_run_api_without_metadata(monkeypatch, tmp_path):
    import obs_lab_phase_c_run as runner
    from test_obs_lab_scores import evidence

    raw = evidence()
    count = 0

    def api(base, token, path):
        nonlocal count
        if path.endswith("/runs"):
            count += 1
            return [{"run_id": "old", "thread_id": "thread", "status": "success"}] + (
                [{"run_id": "new", "thread_id": "thread", "status": "success"}] if count > 1 else [])
        return raw["state"] if path.endswith("/state") else raw["history"]

    class Response:
        def __enter__(self):
            return iter([b"event: end\n", b"data: {}\n", b"\n"])

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *a, **kw: Response())
    row = runner.collect_turn("http://127.0.0.1:1234", "synthetic", "thread", "S10", "batch", 1,
                              30, tmp_path / "private.json")
    assert row["run_id"] == "new"
    assert row["rule_checks"]["rules"]["tool_protocol_valid"]["status"] == "PASS"
    assert json.loads((tmp_path / "private.json").read_text())["prior_run_ids"] == ["old"]
