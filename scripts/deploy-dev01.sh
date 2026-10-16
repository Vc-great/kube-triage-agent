#!/usr/bin/env bash
# Source sync only: preserves remote private config/data; no --delete.
set -euo pipefail
cd "$(dirname "$0")/.."
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev01 \
  'test "$(hostname)" = dev01 && test -w /www/app && mkdir -p /www/app/kube-triage-agent'
rsync -az --exclude='.git/' --exclude='.local/' --exclude='.env' \
  --exclude='.env.local' --exclude='.venv/' --exclude='node_modules/' \
  --exclude='.next/' --exclude='.idea/' --exclude='__pycache__/' \
  --exclude='.pytest_cache/' --exclude='.ruff_cache/' --exclude='backups/' \
  --exclude='*.log' --exclude='output/' --exclude='.playwright-cli/' \
  -e 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes' \
  ./ dev01:/www/app/kube-triage-agent/
echo '源码同步完成；私有配置、Reader 与 Repairer 凭据需单独准备。'
