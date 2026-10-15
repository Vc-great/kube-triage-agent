"""Fixed synthetic Gate A/B comparison; no provider, Kubernetes or network calls."""

import asyncio
import json
import os

from kube_triage import graph as agent
from kube_triage.context import ContextConfig, build_context_view, estimate_context
from kube_triage.mcp_client import ALLOWED_TOOLS, build_model_tool_schemas
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

BUDGET = 6500
MARKER = "SYNTHETIC_PENDING_UID_OLD"
SCHEMAS = build_model_tool_schemas({name: object() for name in ALLOWED_TOOLS})
SUMMARY = {"version": 1, "not_current_evidence": True, "history_notes": [{
    "round_ref": 1, "history_question": "历史诊断", "observation": MARKER,
    "uncertainty": "当前状态未核验"}]}


class FakeModel:
    def __init__(self):
        self.summary_calls = 0
        self.seen = []

    def bind_tools(self, tools):
        assert len(tools) == 4
        return FakeBound(self)

    def bind(self, **kwargs):
        assert kwargs == {"max_tokens": 512}
        return self

    async def ainvoke(self, messages):
        self.summary_calls += 1
        assert MARKER in messages[1].content
        return AIMessage(content=json.dumps(SUMMARY, ensure_ascii=False))


class FakeBound:
    def __init__(self, source):
        self.source = source

    async def ainvoke(self, messages):
        self.source.seen.append(messages)
        return AIMessage(content="历史参考不能证明当前状态")


def fixture(count):
    messages = []
    for number in range(count):
        ident = f"historical-{number}"
        messages.extend([HumanMessage(content=f"历史问题 {number}"),
                         AIMessage(content="", name="triage_llm", tool_calls=[{
                             "name": "events_list", "args": {"namespace": "kube-triage-demo"},
                             "id": ident}]),
                         ToolMessage(content=json.dumps({
                             "ok": True, "result": (MARKER if number == 0 else "x" * 180)}),
                                     tool_call_id=ident),
                         AIMessage(content="历史判断", name="triage_llm")])
    return [*messages, HumanMessage(content="当前状态？")]


async def run_case(count):
    raw = fixture(count)
    model = FakeModel()
    agent.chat_model = lambda: model

    async def tools():
        return {name: object() for name in ALLOWED_TOOLS}

    agent._allowed_tools = tools
    prompt = agent.system_prompt()
    gate_a = build_context_view(prompt, SCHEMAS, raw, ContextConfig(True, BUDGET))
    first = await agent._llm({"messages": raw})
    view = model.seen[0]
    cache = first.get("context_summary", {})
    first_calls = model.summary_calls
    next_raw = [*raw, *first["messages"], HumanMessage(content="请重新读取当前状态")]
    await agent._llm({"messages": next_raw, "context_summary": cache})
    return {"rounds": count,
            "gate_a": {"estimated_input": gate_a.estimated_tokens,
                       "omitted_rounds": gate_a.omitted_rounds, "summary_calls": 0,
                       "cache_hits": 0,
                       "synthetic_marker_retained": int(MARKER in json.dumps(
                           [m.model_dump(mode="json") for m in gate_a.messages]))},
            "gate_b": {"estimated_input": estimate_context(view[0].content, SCHEMAS, view[1:]),
                       "omitted_rounds": (cache["covered_rounds"] if cache.get("status") == "ready"
                                          else gate_a.omitted_rounds),
                       "summary_calls": first_calls,
                       "cache_hits": int(first_calls > 0 and model.summary_calls == first_calls and
                                         cache.get("status") == "ready"),
                       "summary_output_length": len(json.dumps(cache.get("summary", {}),
                                                               ensure_ascii=False)) if
                       cache.get("status") == "ready" else 0,
                       "synthetic_marker_retained": int(MARKER in json.dumps(
                           [m.model_dump(mode="json") for m in view])),
                       "fail_reason": cache.get("error_code")},
            "actual_input_tokens": "UNKNOWN", "summary_input_tokens": "UNKNOWN",
            "summary_output_tokens": "UNKNOWN", "cost": "UNKNOWN",
            "provider_latency": "NOT RUN"}


async def main():
    os.environ["CONTEXT_WINDOW_ENABLED"] = "true"
    os.environ["CONTEXT_SUMMARY_ENABLED"] = "true"
    os.environ["CONTEXT_ESTIMATED_TOTAL_BUDGET"] = str(BUDGET)
    os.environ["REPAIR_ENABLED"] = "false"
    print(json.dumps([await run_case(n) for n in (10, 20, 30)], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
