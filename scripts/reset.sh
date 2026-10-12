#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="${COMPOSE_PROJECT_NAME:?Set explicit project name}"
echo "Only $project Compose volumes may be removed:"
docker volume ls --filter "label=com.docker.compose.project=$project" --format '{{.Name}}'
read -r -p "Type DELETE $project to remove these project volumes: " answer
[[ "$answer" == "DELETE $project" ]] || { echo 'Cancelled'; exit 1; }
exec ./scripts/compose.sh down --volumes
