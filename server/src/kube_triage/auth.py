"""Single-user demo authentication for Aegra's Agent Protocol routes."""

import os
import secrets

from langgraph_sdk import Auth

EXPECTED_TOKEN = os.environ.get("DEMO_API_TOKEN", "")
if not EXPECTED_TOKEN or EXPECTED_TOKEN == "REPLACE_WITH_RANDOM_URL_SAFE_TOKEN":
    raise RuntimeError("DEMO_API_TOKEN must be configured before starting Aegra")

auth = Auth()


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    supplied = next((value for key, value in headers.items() if key.lower() == "x-api-key"), "")
    if not supplied or not secrets.compare_digest(supplied, EXPECTED_TOKEN):
        raise ValueError("Invalid API key")
    return {"identity": "demo-user", "is_authenticated": True}
