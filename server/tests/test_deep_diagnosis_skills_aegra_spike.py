"""Issue #75 S1：Aegra 原生 factory/auth 扩展点；无 DB、服务或端口。

该文件只验证最小契约，不注册 HTTP Skills Graph，不宣称完整 S3/S5 通过。
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

CASES = ["state-dict", "state-list", "state-empty", "state-copy", "state-checkpoint",
         "state-checkpoint-dict", "state-namespace", "state-fake-context", "read-shim",
         "read-get", "metadata-patch", "create-reserved", "loader-copy-resume"]


@pytest.mark.parametrize("scenario", CASES)
def test_aegra_skills_extension_point(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(TRIAGE_ENV="test", LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            env=env, capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["scenario"] == scenario


def probe(scenario):
    def denied(*args, **kwargs):
        raise AssertionError("Aegra Skills Spike 禁止网络、真实 DB/Reader/Provider")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied

    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    import httpx
    from aegra_api.api import threads
    from aegra_api.core import auth_handlers
    from aegra_api.core.auth_deps import get_current_user, require_auth
    from aegra_api.core.database import db_manager
    from aegra_api.models import User
    from aegra_api.services.graph_factory import classify_factory
    from aegra_api.services.langgraph_service import LangGraphService
    from fastapi import FastAPI, HTTPException
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph_sdk import Auth
    from langgraph_sdk.runtime import ServerRuntime
    from pydantic import Field

    from kube_triage import deep_diagnosis_skills as skills
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel

    class Quiet(ProtocolFakeModel):
        inputs: list = Field(default_factory=list)

        def _reply(self, messages):
            self.inputs.append(messages)
            return AIMessage(content="你好，仅合成协议验证。")

    skills.planning.baseline.call_tool = denied
    model, saver, contexts = Quiet(), MemorySaver(), []
    graph_id = "skills-extension-spike-only"

    def factory(config: RunnableConfig, runtime: ServerRuntime):
        # Actual native ServerRuntime, not a client config/context claim.
        contexts.append(runtime.access_context)
        if runtime.access_context == "threads.update":
            raise HTTPException(403, "Skills Spike 禁止客户端 State 写入与派生")
        return skills.build_graph(model)

    classify_factory(factory, graph_id)
    service = LangGraphService()
    service._graph_factories[graph_id] = factory
    user = User(identity="skills-synthetic-user")
    config = {"configurable": {"thread_id": "skills-synthetic-thread"}}
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=SimpleNamespace(metadata_json={"graph_id": graph_id})),
        execute=AsyncMock(side_effect=denied), commit=AsyncMock(side_effect=denied),
    )
    auth = Auth()

    @auth.on.threads.update
    async def deny_metadata(ctx, value):
        return False

    @auth.on.threads.create
    async def guard_create(ctx, value):
        return not value.get("initial_state") and not set(value.get("metadata") or {}) & {
            "graph_id", "skills_revision", "skills_binding"}

    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[threads.get_session] = lambda: session
    app.include_router(threads.router)

    async def run():
        async with service.get_graph(graph_id, config=config,
                                     access_context="threads.create_run", user=user) as graph:
            assert graph.checkpointer is saver, "Aegra 原生 copy 未注入 Checkpointer"
            if scenario == "loader-copy-resume":
                # Both native copy(update=...) and with_config are exercised;
                # this is not evidence for a future facade implementation.
                graph = graph.with_config(config)
                await graph.ainvoke({"messages": [HumanMessage(content="你好")]},
                                    interrupt_before=["SkillsMiddleware.before_model"])
                assert not model.inputs
                await graph.ainvoke(None)
                assert len(model.inputs) == 1
                return
            await graph.ainvoke({"messages": [HumanMessage(content="你好")]}, config)
            before = await graph.aget_state(config)
            history_before = [item.config for item in saver.list(config)]
        calls_before = len(model.inputs)
        bodies = {
            "state-dict": {"values": {"pinned_skills": list(skills.NAMES)}},
            "state-list": {"values": [{"files": {}}, {"pinned_skills": list(skills.NAMES)}]},
            "state-empty": {"values": {}},
            "state-copy": {"values": None, "as_node": "__copy__"},
            "state-checkpoint": {"values": None, "checkpoint_id": "synthetic-checkpoint"},
            "state-checkpoint-dict": {"checkpoint": {"checkpoint_id": "synthetic-checkpoint"}},
            "state-namespace": {"values": {}, "checkpoint_ns": "forged"},
            "state-fake-context": {"values": {"access_context": "threads.read",
                                              "pinned_skills": list(skills.NAMES)}},
            "read-shim": {"values": None},
        }
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://synthetic.invalid") as client:
            if scenario in bodies:
                response = await client.post("/threads/skills-synthetic-thread/state",
                                             json=bodies[scenario])
            elif scenario == "read-get":
                response = await client.get("/threads/skills-synthetic-thread/state")
            elif scenario == "metadata-patch":
                response = await client.patch("/threads/skills-synthetic-thread", json={
                    "metadata": {"graph_id": graph_id, "skills_revision": "forged"}})
            elif scenario == "create-reserved":
                response = await client.post("/threads", json={
                    "metadata": {"graph_id": graph_id, "skills_binding": "forged"}})
            else:
                raise AssertionError(scenario)
        read = scenario in {"read-shim", "read-get"}
        assert response.status_code == (200 if read else 403), (response.status_code, response.text)
        if scenario in bodies and not read:
            assert contexts[-1] == "threads.update"
        if read:
            assert contexts[-1] == "threads.read"
            assert response.json()["values"]["messages"]
        assert len(model.inputs) == calls_before
        async with service.get_graph(graph_id, config=config,
                                     access_context="threads.read", user=user) as graph:
            after = await graph.aget_state(config)
        assert after.config == before.config and after.values == before.values
        assert [item.config for item in saver.list(config)] == history_before
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()

    with patch.object(db_manager, "get_checkpointer", return_value=saver), \
         patch.object(db_manager, "get_store", return_value=None), \
         patch("aegra_api.services.langgraph_service.get_langgraph_service", return_value=service), \
         patch.object(auth_handlers, "get_auth_instance", return_value=auth):
        asyncio.run(run())
    return {"scenario": scenario, "access_contexts": contexts,
            "scope": "ASGI/native-factory/MemorySaver; no deployed service"}


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1]), ensure_ascii=False))
