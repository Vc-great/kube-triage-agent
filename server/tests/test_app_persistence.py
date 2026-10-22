"""Synthetic business persistence checks; PG tests require an explicit isolated DB URL."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest

from kube_triage import app_routes, app_storage, mcp_client


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("ISSUE78_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicit ISSUE78_TEST_DATABASE_URL for isolated PostgreSQL")
    from aegra_api.settings import settings

    monkeypatch.setattr(settings.db, "DATABASE_URL", url)
    monkeypatch.setenv("APP_EVIDENCE_ENABLED", "true")
    monkeypatch.setenv("APP_HISTORY_ENABLED", "true")
    asyncio.run(app_storage.migrate())


def test_visible_messages_exclude_tools_reasoning_and_empty_ai():
    result = app_storage.visible_messages({"values": {"messages": [
        {"type": "human", "content": "重复"},
        {"type": "ai", "content": "", "tool_calls": [{"id": "call"}]},
        {"type": "tool", "content": "internal"},
        {"type": "ai", "content": [{"type": "reasoning", "text": "internal"},
                                   {"type": "text", "text": "可见"}]},
        {"type": "human", "content": "重复"},
    ]}}, "partial")
    assert [m["role"] for m in result] == ["human", "assistant", "human"]
    assert result[0]["source_message_id"] != result[-1]["source_message_id"]
    assert result[1]["content"] == [{"type": "text", "text": "可见"}]
    assert result[1]["status"] == "partial"


@pytest.mark.parametrize("failure,expected", [
    (None, None), (ValueError("HTTP 403 forbidden"), "forbidden"),
    (ValueError("HTTP 404 not found"), "not_found"), (TimeoutError(), "timeout"),
])
def test_reader_evidence_sql_and_api(pg, monkeypatch, failure, expected):
    calls = []
    thread = str(uuid4())

    class Tool:
        async def ainvoke(self, args):
            calls.append(args)
            if failure:
                raise failure
            return "合成" * 18000

    async def discover():
        return {"pods_log": Tool()}

    monkeypatch.setattr(mcp_client, "_allowed_tools", discover)

    async def run():
        with app_storage.reader_context(graph_id="agent", tool_call_id="reader-1"):
            result = await mcp_client.call_tool("pods_log", {
                "namespace": mcp_client.NAMESPACE, "name": "synthetic-pod"}, thread)
        assert result["evidence_persisted"] is True
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_routes.app),
                                     base_url="http://test") as client:
            response = await client.get(f'/app/evidence/{result["evidence_id"]}')
            assert response.status_code == 200
            row = response.json()
        assert row["thread_id"] == thread and row["tool_call_id"] == "reader-1"
        assert row["graph_id"] == "agent" and row["run_id"] is None
        assert row["arguments"]["tail"] == 20
        assert row["error_type"] == expected
        assert row["sha256"] == app_storage.digest(row["payload"])
        if failure:
            assert row["status"] == "failed" and result["ok"] is False
        else:
            assert row["status"] == "success" and row["is_truncated"]
            assert len(row["payload"]["result"]) == 16384 + len("\n[结果已截断]")

    asyncio.run(run())
    assert len(calls) == 1


def test_reader_db_failure_does_not_repeat_mcp(monkeypatch, caplog):
    monkeypatch.setenv("APP_EVIDENCE_ENABLED", "true")
    calls = []

    class Tool:
        async def ainvoke(self, args):
            calls.append(args)
            return "合成结果"

    async def discover():
        return {"events_list": Tool()}

    async def offline():
        raise OSError("synthetic-secret-must-not-be-logged")

    monkeypatch.setattr(mcp_client, "_allowed_tools", discover)
    monkeypatch.setattr(app_storage, "connect", offline)
    response = asyncio.run(mcp_client.call_tool("events_list", {"namespace": mcp_client.NAMESPACE}))
    assert response["ok"] is True and response["result"] == "合成结果"
    assert response["evidence_persisted"] is False and "evidence_id" not in response
    assert len(calls) == 1
    assert "synthetic-secret" not in caplog.text


def test_disabled_store_preserves_original_response(monkeypatch):
    monkeypatch.delenv("APP_EVIDENCE_ENABLED", raising=False)
    monkeypatch.delenv("APP_HISTORY_ENABLED", raising=False)

    async def denied():
        raise AssertionError("disabled path must not connect")

    monkeypatch.setattr(app_storage, "connect", denied)
    payload = {"ok": True, "result": "合成"}
    assert asyncio.run(app_storage.persist_evidence("events_list", {}, None, payload, False)) is payload

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_routes.app),
                                     base_url="http://test") as client:
            assert (await client.post('/app/history/sync', json={"thread_id": "old"})).status_code == 404

    asyncio.run(request())


def test_history_turns_idempotency_versions_pagination_and_lifecycle(pg):
    thread = str(uuid4())
    state = {"checkpoint": {"checkpoint_id": "checkpoint-1"}, "values": {"messages": []}}
    run = {"status": "success"}

    async def read():
        return state, {"metadata": {"graph_id": "agent"}, "status": "idle"}, run

    async def check():
        await app_storage.migrate()  # second DDL application preserves records
        for turn in range(10):
            state["checkpoint"]["checkpoint_id"] = f"checkpoint-{turn}"
            state["values"]["messages"].extend([
                {"type": "human", "id": f"h-{turn}", "content": "同样的提问"},
                {"type": "ai", "id": f"a-{turn}", "content": "同样的回答"},
            ])
            assert (await app_storage.sync_history(thread, read))["added"] == 2
            assert (await app_storage.sync_history(thread, read))["added"] == 0
        page = await app_storage.get_history(thread, 7, 0, None)
        assert len(page["messages"]) == 7 and page["next_cursor"] == 7
        rest = await app_storage.get_history(thread, 200, 7, page["checkpoint_id"])
        assert len(rest["messages"]) == 13
        assert all(m["status"] == "completed" for m in page["messages"] + rest["messages"])
        # Same ID, changed text: preserve old version, project current branch.
        state["values"]["messages"][-1]["content"] = "重新生成"
        state["checkpoint"]["checkpoint_id"] = "regenerated"
        assert (await app_storage.sync_history(thread, read))["added"] == 1
        rows = (await app_storage.get_history(thread, 200, 0, None))["messages"]
        assert len(rows) == 20 and rows[-1]["content"] == "重新生成"
        async with await app_storage.connect() as conn:
            old = await (await conn.execute("""
                SELECT * FROM app_conversation_messages
                WHERE thread_id=%s AND source_message_id='a-9' AND NOT active
                """, (thread,))).fetchone()
            assert old["content"] == "同样的回答"
        with pytest.raises(ValueError, match="checkpoint_changed"):
            await app_storage.get_history(thread, 200, 7, page["checkpoint_id"])
        # Unfinished, failed and cancelled responses never become completed.
        for lifecycle in ["pending", "error", "interrupted"]:
            run["status"] = lifecycle
            state["values"]["messages"].extend([
                {"type": "human", "id": str(uuid4()), "content": lifecycle},
                {"type": "ai", "id": str(uuid4()), "content": "部分回复"}])
            await app_storage.sync_history(thread, read)
            rows = (await app_storage.get_history(thread, 200, 0, None))["messages"]
            assert rows[-1]["status"] != "completed"
            assert rows[1]["status"] == "completed"
        assert (await app_storage.get_history(str(uuid4()), 100, 0, None))["status"] == "legacy"
        # Aegra static interrupt may report Run=success with pending State.next.
        run["status"] = "success"
        state["next"] = ["llm"]
        assert (await app_storage.sync_history(thread, read))["status"] == "interrupted"

    asyncio.run(check())
