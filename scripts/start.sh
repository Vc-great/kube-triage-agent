#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -e .env ]]; then
  python3 - <<'PY'
from pathlib import Path
import secrets
import os

example = Path('.env.example').read_text()
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write(example.replace('POSTGRES_PASSWORD=\n', 'POSTGRES_PASSWORD=' + secrets.token_urlsafe(32) + '\n').replace('DEMO_API_TOKEN=\n', 'DEMO_API_TOKEN=' + secrets.token_urlsafe(32) + '\n'))
PY
  echo 'Created local .env with a random project-only PostgreSQL password.'
fi
if [[ "${1:-}" == "--init-only" ]]; then
  exit 0
fi
if ! grep -Eq '^POSTGRES_PASSWORD=.+$' .env || ! grep -Eq '^DEMO_API_TOKEN=.+$' .env; then
  echo 'Set non-empty POSTGRES_PASSWORD and DEMO_API_TOKEN; existing .env was not changed.' >&2
  exit 2
fi
python3 scripts/check-ports.py
./scripts/compose.sh config --quiet
./scripts/compose.sh up -d --build --wait
