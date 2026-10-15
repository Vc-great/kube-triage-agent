"""Single-user demo authentication for Aegra's Agent Protocol routes."""

import os
import secrets

from langgraph_sdk import Auth

from kube_triage.config import (
    ConfigurationError,
    incident_memory_http_write_blocked,
    incident_memory_provenance_key,
)

EXPECTED_TOKEN = os.environ.get("DEMO_API_TOKEN", "")
if not EXPECTED_TOKEN or EXPECTED_TOKEN == "REPLACE_WITH_RANDOM_URL_SAFE_TOKEN":
    raise RuntimeError("DEMO_API_TOKEN must be configured before starting Aegra")

auth = Auth()
MEMORY_HTTP_WRITE_BLOCKED = incident_memory_http_write_blocked()
if MEMORY_HTTP_WRITE_BLOCKED:
    incident_memory_provenance_key()  # Fail startup before exposing the HTTP service.


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    supplied = next((value for key, value in headers.items() if key.lower() == "x-api-key"), "")
    if not supplied or not secrets.compare_digest(supplied, EXPECTED_TOKEN):
        raise ValueError("Invalid API key")
    return {"identity": "demo-user", "is_authenticated": True}


@auth.on.store.put
async def guard_http_store_put(ctx, value: dict):
    # Aegra 0.10.8 invokes this hook for HTTP routes only. Graph Runtime.store
    # bypasses it. Deny every HTTP write to avoid namespace-prefix ambiguities.
    try:
        return False if incident_memory_http_write_blocked() else None
    except ConfigurationError:
        return False


@auth.on.store.delete
async def guard_http_store_delete(ctx, value: dict):
    try:
        return False if incident_memory_http_write_blocked() else None
    except ConfigurationError:
        return False
