"""Small PostgreSQL business store; independent of Aegra's checkpoint schema."""

import asyncio
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from kube_triage.config import ConfigurationError

logger = logging.getLogger(__name__)
_reader_context = ContextVar("reader_evidence_context", default=None)
STORAGE_TIMEOUT = 5


def enabled(kind: str) -> bool:
    name = f"APP_{kind.upper()}_ENABLED"
    raw = os.getenv(name, "false")
    if raw not in {"true", "false"}:
        raise ConfigurationError(f"{name} 必须为 true 或 false")
    return raw == "true"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


async def connect():
    # Reuse the runtime's supported DATABASE_URL / POSTGRES_* normalization.
    from aegra_api.settings import settings

    return await psycopg.AsyncConnection.connect(
        settings.db.database_url_sync, connect_timeout=3,
        options="-c statement_timeout=3000 -c lock_timeout=3000", row_factory=dict_row)


async def migrate():
    async with asyncio.timeout(STORAGE_TIMEOUT):
        async with await connect() as conn:
            await conn.execute(Path(__file__).with_name("migrations").joinpath(
                "001_app.sql").read_text())


@contextmanager
def reader_context(*, graph_id: str, tool_call_id: str, run_id: str | None = None):
    """Host execution metadata only; never reconstruct it from model output."""
    token = _reader_context.set({"graph_id": graph_id, "tool_call_id": tool_call_id,
                                 "run_id": run_id})
    try:
        yield
    finally:
        _reader_context.reset(token)


async def persist_evidence(name: str, arguments: dict, thread_id: str | None,
                           payload: dict, truncated: bool) -> dict:
    if not enabled("evidence"):
        return payload
    ident = str(uuid4())
    observed_at = datetime.now(UTC)
    context = _reader_context.get() or {}
    try:
        async with asyncio.timeout(STORAGE_TIMEOUT):
            async with await connect() as conn:
                await conn.execute("""
                    INSERT INTO app_evidence
                        (id, thread_id, graph_id, run_id, tool_call_id, tool_name, namespace,
                         resource_name, arguments, status, error_type, payload,
                         is_truncated, sha256, observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (ident, thread_id, context.get("graph_id"), context.get("run_id"),
                          context.get("tool_call_id"),
                          name, arguments["namespace"], arguments.get("name"), Jsonb(arguments),
                          "success" if payload["ok"] else "failed", payload.get("error_type"),
                          Jsonb(payload), truncated, digest(payload), observed_at))
        return {**payload, "evidence_id": ident, "evidence_persisted": True,
                "is_truncated": truncated}
    except Exception as exc:  # noqa: BLE001 - bounded optional archive boundary
        # Do not log payload, DB URL, exception text or credentials.
        logger.warning("evidence_persistence_failed exception_type=%s", type(exc).__name__)
        return {**payload, "evidence_persisted": False, "is_truncated": truncated}


async def get_evidence(ident: str):
    async with await connect() as conn:
        return await (await conn.execute(
            "SELECT * FROM app_evidence WHERE id = %s", (ident,))).fetchone()


def visible_messages(state: dict, status: str) -> list[dict]:
    """Keep visible text/blocks, excluding tools, reasoning and internal control messages."""
    result = []
    messages = state.get("values", {}).get("messages", [])
    last_human = max((i for i, m in enumerate(messages) if m.get("type") == "human"), default=-1)
    for index, message in enumerate(messages):
        kind = message.get("type")
        if kind not in {"human", "ai"}:
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = [block for block in content if isinstance(block, str) or
                       isinstance(block, dict) and block.get("type") in {
                           "text", "image_url", "image", "file", "audio"}]
        if not content:
            continue
        # Position distinguishes identical questions without IDs in different turns.
        source = message.get("id") or f"fallback:{index}:{kind}"
        result.append({"source_message_id": source,
                       "role": "human" if kind == "human" else "assistant",
                       "content": content, "content_sha256": digest(content),
                       "status": ("completed" if kind == "human" else
                                  status if index > last_human else "partial"),
                       "current_turn": index > last_human})
    return result


async def sync_history(thread_id: str, read_state):
    """Serialize state reads and commits per thread across server workers."""
    async with await connect() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 78))", (thread_id,))
        state, thread, run = await read_state()
        # Only a finished Run may certify Assistant completion.
        run_status = run.get("status") if run else None
        paused = (state.get("next") or state.get("interrupts") or
                  any(task.get("interrupts") for task in state.get("tasks", [])) or
                  thread.get("status") == "interrupted")
        status = ("failed" if run_status in {"error", "timeout"} else
                  "cancelled" if run_status in {"interrupted", "cancelled"} else
                  "interrupted" if paused else
                  "completed" if run_status == "success" else
                  "partial")
        messages = visible_messages(state, status)
        if not messages:
            return {"status": "legacy", "added": 0, "updated": 0}
        checkpoint = (state.get("checkpoint") or {}).get("checkpoint_id")
        title = next((m["content"] for m in messages if m["role"] == "human"), "Conversation")
        if isinstance(title, list):
            title = " ".join(block if isinstance(block, str) else block.get("text", "")
                             for block in title)
        if not isinstance(title, str):
            title = "Conversation"
        await conn.execute("""
            INSERT INTO app_conversations(thread_id,graph_id,title,status,checkpoint_id)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (thread_id) DO UPDATE SET
            status=EXCLUDED.status, checkpoint_id=EXCLUDED.checkpoint_id, updated_at=now()
            """, (thread_id, thread.get("metadata", {}).get("graph_id"), title[:120],
                  status, checkpoint))
        # Preserve all prior versions; active + position is the latest branch projection.
        await conn.execute("UPDATE app_conversation_messages SET active=false WHERE thread_id=%s",
                           (thread_id,))
        added = updated = 0
        # Run IDs are not inferred for historical messages from the latest Run.
        for position, message in enumerate(messages):
            previous = await (await conn.execute("""
                SELECT id,status FROM app_conversation_messages
                WHERE thread_id=%s AND source_message_id=%s AND content_sha256=%s
                """, (thread_id, message["source_message_id"],
                      message["content_sha256"]))).fetchone()
            if previous:
                # Earlier completed messages keep completion when a later Run fails.
                message_status = (previous["status"] if not message["current_turn"]
                                  or previous["status"] == "completed" else message["status"])
                updated += int(previous["status"] != message_status)
                await conn.execute("""
                    UPDATE app_conversation_messages SET active=true,position=%s,status=%s
                    WHERE id=%s
                    """, (position, message_status, previous["id"]))
            else:
                added += 1
                await conn.execute("""
                    INSERT INTO app_conversation_messages
                      (id,thread_id,source_message_id,content_sha256,role,content,
                       position,status,checkpoint_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (str(uuid4()), thread_id, message["source_message_id"],
                          message["content_sha256"], message["role"], Jsonb(message["content"]),
                          position, message["status"], checkpoint))
        return {"status": status, "added": added, "updated": updated,
                "checkpoint_id": checkpoint}


async def get_history(thread_id: str, limit: int, cursor: int, checkpoint: str | None):
    async with await connect() as conn:
        conversation = await (await conn.execute(
            "SELECT * FROM app_conversations WHERE thread_id=%s FOR SHARE", (thread_id,))).fetchone()
        if not conversation:
            return {"status": "legacy", "messages": [], "next_cursor": None}
        if checkpoint and checkpoint != conversation["checkpoint_id"]:
            raise ValueError("history_checkpoint_changed")
        rows = await (await conn.execute("""
            SELECT * FROM app_conversation_messages
            WHERE thread_id=%s AND active AND position>=%s ORDER BY position LIMIT %s
            """, (thread_id, cursor, limit + 1))).fetchall()
        return {"status": conversation["status"], "messages": rows[:limit],
                "checkpoint_id": conversation["checkpoint_id"],
                "next_cursor": rows[limit]["position"] if len(rows) > limit else None}


if __name__ == "__main__":
    asyncio.run(migrate())
    print("app_* migration applied (idempotent; runtime tables untouched)")
