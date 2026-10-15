"""Spike-only HTTP Store write guard. Never loaded by the product config."""

import os
import secrets

from langgraph_sdk import Auth

auth = Auth()


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    expected = os.environ["DEMO_API_TOKEN"]
    supplied = next((v for k, v in headers.items() if k.lower() == "x-api-key"), "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise ValueError("Invalid API key")
    return {"identity": "demo-user", "is_authenticated": True}


def protected(namespace: object) -> bool:
    if not isinstance(namespace, list):
        return False
    # Aegra's HTTP path adds (users, demo-user) after the hook. Cover both
    # names clients may send, including an explicitly prefixed namespace.
    parts = namespace[:]
    if parts[:2] == ["users", "demo-user"]:
        parts = parts[2:]
    return parts[:1] == ["kube-triage"] and "incidents" in parts


@auth.on.store.put
async def forbid_incident_put(ctx, value: dict):
    if protected(value.get("namespace")):
        return False
    return None


@auth.on.store.delete
async def forbid_incident_delete(ctx, value: dict):
    if protected(value.get("namespace")):
        return False
    return None
