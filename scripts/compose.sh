#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env; copy .env.example and set a unique POSTGRES_PASSWORD" >&2
  exit 2
fi
if grep -q '^POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_URL_SAFE_PASSWORD$' .env; then
  echo "Set a unique POSTGRES_PASSWORD in .env first." >&2
  exit 2
fi
exec docker compose -p kube-triage-agent --env-file .env -f infra/compose.yaml "$@"
