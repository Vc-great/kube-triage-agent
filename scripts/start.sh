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
    file.write(example.replace('REPLACE_WITH_RANDOM_URL_SAFE_PASSWORD', secrets.token_urlsafe(32)).replace('REPLACE_WITH_RANDOM_URL_SAFE_TOKEN', secrets.token_urlsafe(32)))
PY
  echo 'Created local .env with a random project-only PostgreSQL password.'
fi
if ! grep -q '^DEMO_API_TOKEN=' .env; then
  echo "DEMO_API_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
fi
if grep -q '^POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_URL_SAFE_PASSWORD$' .env; then
  echo 'Set a unique POSTGRES_PASSWORD in .env first.' >&2
  exit 2
fi
if grep -q '^DEMO_API_TOKEN=REPLACE_WITH_RANDOM_URL_SAFE_TOKEN$' .env || ! grep -q '^DEMO_API_TOKEN=.' .env; then
  echo 'Set a unique DEMO_API_TOKEN in .env first.' >&2
  exit 2
fi
python3 scripts/check-ports.py
./scripts/compose.sh config --quiet
./scripts/compose.sh up -d --build --wait
