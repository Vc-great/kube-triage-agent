"""Phase 3：锁定 SDK 的真实工具协程 → 唯一 Evidence Writer → 隔离 PG。"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from kube_triage import app_storage as storage
from kube_triage.deep_diagnosis import ReaderBoundary


@pytest.mark.parametrize("graph", ["deep_diagnosis", "deep_diagnosis_planning",
                                  "deep_diagnosis_skills"])
def test_sdk_parallel_provenance_failures_and_budget(graph):
    url = os.getenv("ISSUE78_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicit isolated PostgreSQL")
    env = {**os.environ, "DATABASE_URL": url, "APP_EVIDENCE_ENABLED": "true",
           "APP_HISTORY_ENABLED": "true", "TRIAGE_ENV": "test",
           "TRIAGE_MOCK_DATASET": "memory-web", "LANGSMITH_TRACING": "false",
           "OTEL_SDK_DISABLED": "true"}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), graph],
                            env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["graph"] == graph


def test_reader_context_parallel_cancel_and_exception_cleanup():
    async def scenario():
        boundary = ReaderBoundary()
        started = asyncio.Event()
        request = SimpleNamespace(tool_call={"id": "cancelled"}, runtime=SimpleNamespace(
            config={"configurable": {"thread_id": "cancel-thread"}}))

        async def wait(_):
            assert storage._reader_context.get()["thread_id"] == "cancel-thread"
            started.set()
            await asyncio.Event().wait()

        async def cancelled():
            try:
                await boundary._execute_reader(request, wait)
            finally:
                assert storage._reader_context.get() is None

        task = asyncio.create_task(cancelled())
        await started.wait()
        assert storage._reader_context.get() is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async def fail(_):
            raise ValueError("synthetic")

        with storage.reader_context(graph_id="outer", tool_call_id="outer"):
            with pytest.raises(ValueError):
                await boundary._execute_reader(request, fail)
            assert storage._reader_context.get()["graph_id"] == "outer"
        assert storage._reader_context.get() is None

    asyncio.run(scenario())


async def sdk_probe(graph_id):
    from importlib import import_module

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from kube_triage import mcp_client
    from kube_triage.deep_diagnosis_planning_fake import PlanningProtocolFakeModel

    module = import_module("kube_triage." + graph_id)
    executions = []

    class Model(PlanningProtocolFakeModel):
        def _reply(self, messages):
            human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            turn = messages[messages.index(human):]
            if any(isinstance(m, ToolMessage) for m in turn):
                return AIMessage(content="合成回执；未知 UNKNOWN")
            if human.content == "budget":
                calls = [("events_list", {"namespace": mcp_client.NAMESPACE})] * 7
            elif human.content == "errors":
                calls = [("pods_get", {"namespace": mcp_client.NAMESPACE, "name": "forbidden"}),
                         ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "timeout"})]
            else:
                calls = [("events_list", {"namespace": mcp_client.NAMESPACE}),
                         ("pods_list_in_namespace", {"namespace": mcp_client.NAMESPACE})]
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": f"p3-{index}"}
                for index, (name, args) in enumerate(calls)])

    class Tool:
        async def ainvoke(self, args):
            before = dict(storage._reader_context.get())
            executions.append(before)
            await asyncio.sleep(.01)
            assert storage._reader_context.get() == before
            if args.get("name") == "forbidden":
                raise ValueError("HTTP 403 forbidden")
            if args.get("name") == "timeout":
                raise TimeoutError()
            return "synthetic Reader result"

    async def discover():
        return {name: Tool() for name in mcp_client.ALLOWED_TOOLS}

    mcp_client._allowed_tools = discover
    await storage.migrate()
    graph = module.build_graph(Model())

    async def run(prompt):
        thread = str(uuid4())
        result = await graph.ainvoke({"messages": [HumanMessage(content=prompt)]},
                                    {"configurable": {"thread_id": thread}})
        tools = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        persisted = []
        for tool in tools:
            payload = json.loads(tool.content) if tool.content.startswith("{") else {}
            if "evidence_id" not in payload:
                assert prompt == "budget" and "预算" in tool.content
                continue
            row = await storage.get_evidence(payload["evidence_id"])
            assert row["thread_id"] == thread and row["graph_id"] == graph_id
            assert row["tool_call_id"] == tool.tool_call_id and row["run_id"] is None
            assert row["sha256"] == storage.digest(row["payload"])
            assert row["status"] == ("success" if payload["ok"] else "failed")
            assert tool.status == ("success" if payload["ok"] else "error")
            persisted.append(row)
        assert len(persisted) == (6 if prompt == "budget" else 2)
        if prompt == "errors":
            assert {r["error_type"] for r in persisted} == {"forbidden", "timeout"}
        return thread

    first, second = await asyncio.gather(run("parallel"), run("parallel"))
    assert first != second
    await run("errors")
    await run("budget")
    assert len(executions) == 12
    assert storage._reader_context.get() is None

    # Archive failure follows the same real tool path, without a second MCP call.
    async def offline():
        raise OSError("synthetic offline")

    storage.connect = offline
    result = await graph.ainvoke({"messages": [HumanMessage(content="offline")]},
                                {"configurable": {"thread_id": str(uuid4())}})
    tools = [json.loads(m.content) for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(executions) == 14
    assert all(p["ok"] and p["evidence_persisted"] is False and "evidence_id" not in p
               for p in tools)
    print(json.dumps({"graph": graph_id, "executions": len(executions), "persisted": 12}))


if __name__ == "__main__":
    asyncio.run(sdk_probe(sys.argv[1]))
