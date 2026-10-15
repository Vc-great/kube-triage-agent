"""Prepare fresh local-only credentials for the isolated Phase 3-2 probe.

Never prints credentials, changes a user .env, starts a service or touches
an existing file. Run from the repository root; outputs are gitignored.
"""

import argparse
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-port", type=int, default=15442)
    args = parser.parse_args()
    if not 1024 <= args.db_port <= 65535:
        raise SystemExit("invalid db port")
    directory = Path(".local/phase32")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    if any((directory / name).exists() for name in ("env", "env-write", "env-write-only")):
        raise SystemExit("Phase 3-2 env already exists; refusing to overwrite")
    password = secrets.token_urlsafe(32)
    common = {
        "PHASE30_DB_USER": "phase32",
        "PHASE30_DB_PASSWORD": password,
        "PHASE30_DB_NAME": "phase32",
        "PHASE30_DB_PORT": str(args.db_port),
        "POSTGRES_USER": "phase32",
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": "phase32",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": str(args.db_port),
        "DEMO_API_TOKEN": secrets.token_urlsafe(32),
        "INCIDENT_MEMORY_PROVENANCE_SECRET": secrets.token_urlsafe(48),
        "INCIDENT_MEMORY_ENABLED": "true",
        "TRIAGE_ENV": "test",
        "REPAIR_SIMULATED": "true",
        "REPAIR_ENABLED": "true",
        "LLM_MODEL": "synthetic-fake",
        "LLM_API_KEY": "synthetic-fake",
        "MCP_SERVER_URL": "http://mock-mcp:8000/mcp",
    }
    for name, read, write in (("env", "true", "false"),
                              ("env-write", "true", "true"),
                              ("env-write-only", "false", "true")):
        values = {**common, "INCIDENT_MEMORY_READ_ENABLED": read,
                  "INCIDENT_MEMORY_WRITE_ENABLED": write}
        path = directory / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("prepared three isolated Phase 3-2 env files (mode 0600)")


if __name__ == "__main__":
    main()
