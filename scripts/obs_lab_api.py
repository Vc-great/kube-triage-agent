"""Test-only Aegra entry: drain its existing OTel provider before SIGTERM returns."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

from opentelemetry import trace


def draining_lifespan(original, get_provider=trace.get_tracer_provider):
    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original(app):
                yield
        finally:
            result = {"event": "obs_lab_otel_flush", "completed": False}
            try:
                flush = getattr(get_provider(), "force_flush", None)
                if flush is None:
                    result.update(completed=True, disabled=True)
                else:
                    result["completed"] = await asyncio.to_thread(flush, timeout_millis=10000)
            except Exception as error:  # noqa: BLE001 - export failures cannot alter Agent state
                result["error_type"] = type(error).__name__
            print(json.dumps(result), flush=True)
    return lifespan


def serve(port):
    if (os.getenv("TRIAGE_ENV") != "test" or os.getenv("OBS_LAB_ENTRY") != "true"
            or os.getenv("REPAIR_ENABLED") != "false"):
        raise RuntimeError("Observability Lab API requires isolated test mode and Repair OFF")
    if os.getenv("OBS_LAB_SCENARIO"):
        if os.environ["OBS_LAB_SCENARIO"] not in {"S04", "S05", "S06", "S07", "S08"}:
            raise RuntimeError("Unknown test-only lab scenario")
        from obs_lab_faults import observed_reader

        from kube_triage import mcp_client

        mcp_client.call_tool = observed_reader(mcp_client.call_tool)
    attempt_client = None
    if os.getenv("OBS_LAB_SCENARIO") == "S07":
        import httpx
        from obs_lab_faults import attempt_transport, observed_model_factory

        from kube_triage import llm

        # Only the test process uses this factory. Graph imports it after installation.
        attempt_client = httpx.AsyncClient(transport=attempt_transport(httpx.AsyncHTTPTransport()))
        llm.chat_model = observed_model_factory(llm.chat_model, attempt_client)
    import uvicorn
    from aegra_api.main import app

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original(app):
                yield
        finally:
            if attempt_client is not None:
                await attempt_client.aclose()

    app.router.lifespan_context = draining_lifespan(lifespan)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    serve(int(sys.argv[1]))
