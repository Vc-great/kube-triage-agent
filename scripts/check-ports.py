#!/usr/bin/env python3
"""Read-only port preflight; never binds or modifies another service."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

values = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

failed = False
owned = set()
try:
    output = subprocess.check_output(["./scripts/compose.sh", "ps", "--format", "json"], text=True, stderr=subprocess.DEVNULL)
    for line in output.splitlines():
        item = json.loads(line)
        if item.get("Project") == os.environ.get("COMPOSE_PROJECT_NAME"):
            for binding in item.get("Publishers", []):
                if binding.get("URL") == "127.0.0.1" and binding.get("PublishedPort"):
                    owned.add((item.get("Service"), binding["PublishedPort"]))
except (OSError, subprocess.CalledProcessError, ValueError):
    pass
if values.get("WEB_PORT", "13000") == values.get("API_PORT", "12026"):
    print("WEB_PORT and API_PORT must differ", file=sys.stderr)
    sys.exit(1)
for name, default in (("WEB_PORT", 13000), ("API_PORT", 12026)):
    port = int(values.get(name, default))
    with socket.socket() as sock:
        sock.settimeout(0.5)
        occupied = sock.connect_ex(("127.0.0.1", port)) == 0
    own_service = "web" if name == "WEB_PORT" else "api"
    is_owned = (own_service, port) in owned
    print(f"{name}={port}: {'owned by this project' if is_owned else 'IN USE' if occupied else 'free'}")
    failed |= occupied and not is_owned
if failed:
    print("Choose unused ports in .env; update NEXT_PUBLIC_API_URL and server/aegra.json CORS, then rebuild web.", file=sys.stderr)
    sys.exit(1)
