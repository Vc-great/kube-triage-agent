#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(hostname)" != dev01 || "$PWD" != /www/app/kube-triage-agent ]]; then
  echo 'Only run this deployment entrypoint on dev01 in /www/app/kube-triage-agent.' >&2
  exit 2
fi
exec python3 scripts/compose_with_langfuse.py dev01 kube-triage-agent "$@"
