#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env; copy .env.example and set a unique POSTGRES_PASSWORD" >&2
  exit 2
fi
if grep -q '^DEMO_API_TOKEN=REPLACE_WITH_RANDOM_URL_SAFE_TOKEN$' .env || ! grep -q '^DEMO_API_TOKEN=.' .env; then
  echo "Set a unique DEMO_API_TOKEN in .env first." >&2
  exit 2
fi
if grep -q '^POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_URL_SAFE_PASSWORD$' .env || ! grep -q '^POSTGRES_PASSWORD=.' .env; then
  echo "Set a unique POSTGRES_PASSWORD in .env first." >&2
  exit 2
fi
if [[ -z "${COMPOSE_PROJECT_NAME:-}" ]]; then
  echo "Set an explicit COMPOSE_PROJECT_NAME after checking project ownership." >&2
  exit 2
fi
exec python3 scripts/compose_with_langfuse.py formal "$COMPOSE_PROJECT_NAME" "$@"
