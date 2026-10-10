#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Only kube-triage-agent Compose volumes may be removed:"
docker volume ls --filter label=com.docker.compose.project=kube-triage-agent --format '{{.Name}}'
read -r -p 'Type DELETE kube-triage-agent to remove these project volumes: ' answer
[[ "$answer" == 'DELETE kube-triage-agent' ]] || { echo 'Cancelled'; exit 1; }
exec ./scripts/compose.sh down --volumes
