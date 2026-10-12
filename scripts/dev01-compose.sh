#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(hostname)" != dev01 || "$PWD" != /www/app/kube-triage-agent ]]; then
  echo 'Only run this deployment entrypoint on dev01 in /www/app/kube-triage-agent.' >&2
  exit 2
fi
exec docker compose -p kube-triage-agent --env-file .env \
  -f infra/compose.yaml -f infra/dev01.compose.yaml "$@"
