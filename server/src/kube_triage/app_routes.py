"""Business routes mounted into the existing Aegra FastAPI application."""

import asyncio
import os
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from kube_triage import app_storage as storage

app = FastAPI()


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(min_length=1, max_length=256)


def require_enabled(kind):
    if not storage.enabled(kind):
        raise HTTPException(404, "功能未启用")


async def protocol_state(request: Request, thread_id: str):
    # In-process Agent Protocol: same app, same auth, no network self-request or external token.
    path = f"/threads/{quote(thread_id, safe='')}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app),
                                 base_url="http://aegra.internal",
                                 headers={"x-api-key": os.environ["DEMO_API_TOKEN"]}) as client:
        async def read(suffix):
            response = await client.get(path + suffix)
            if response.status_code == 404:
                raise HTTPException(404, "Thread 不存在")
            response.raise_for_status()
            return response.json()
        thread = await read("")
        # Busy runs can change state during read; defer until a stable boundary.
        if thread.get("status") == "busy":
            raise HTTPException(409, "Run 进行中，稍后重试历史同步")
        state = await read("/state")
        runs = await read("/runs?limit=1")
        latest = runs[0] if runs else None
        after = await read("")
        if after.get("status") == "busy" or after.get("updated_at") != thread.get("updated_at"):
            raise HTTPException(409, "Thread 已变化，请重试历史同步")
        return state, thread, latest


@app.post("/app/history/sync")
async def sync(body: SyncRequest, request: Request):
    require_enabled("history")
    try:
        async with asyncio.timeout(storage.STORAGE_TIMEOUT):
            return await storage.sync_history(
                body.thread_id, lambda: protocol_state(request, body.thread_id))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - sanitized optional-store failure
        raise HTTPException(503, "历史尚未同步；原 Agent 仍可使用") from None


@app.get("/app/history/threads/{thread_id}/messages")
async def messages(thread_id: str, limit: int = Query(100, ge=1, le=200),
                   cursor: int = Query(0, ge=0), checkpoint: str | None = None):
    require_enabled("history")
    try:
        async with asyncio.timeout(storage.STORAGE_TIMEOUT):
            return await storage.get_history(thread_id, limit, cursor, checkpoint)
    except ValueError:
        raise HTTPException(409, "历史分支已变化，请重新加载") from None
    except Exception:  # noqa: BLE001 - sanitized optional-store failure
        raise HTTPException(503, "历史暂不可用；正在显示实时消息") from None


@app.get("/app/evidence/{evidence_id}")
async def evidence(evidence_id: UUID):
    require_enabled("evidence")
    try:
        async with asyncio.timeout(storage.STORAGE_TIMEOUT):
            row = await storage.get_evidence(str(evidence_id))
    except Exception:  # noqa: BLE001 - sanitized optional-store failure
        raise HTTPException(503, "证据存储暂不可用") from None
    if row is None:
        raise HTTPException(404, "证据不存在")
    return row
