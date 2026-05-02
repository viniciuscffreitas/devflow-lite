#!/usr/bin/env bash
# Deploy the DevFlow analytics dashboard to the remote VPS.
#
# Flow:
#   1. rsync the dashboard/ subtree (source + deploy/) to the VPS
#   2. docker compose build --pull (pick up dependency updates)
#   3. docker compose up -d (idempotent restart)
#
# Never writes credentials. SSH key auth is assumed — run
# `ssh-copy-id vinicius@<host>` once before using this script.
#
# Usage: scripts/deploy_dashboard.sh [host]
#   host: defaults to $DEVFLOW_DASHBOARD_HOST or vinicius@vinicius.xyz
set -euo pipefail

HOST="${1:-${DEVFLOW_DASHBOARD_HOST:-vinicius@vinicius.xyz}}"
REMOTE_DIR="${DEVFLOW_DASHBOARD_REMOTE_DIR:-/home/vinicius/devflow/dashboard}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$REPO_ROOT/dashboard"

if [[ ! -f "$LOCAL_DIR/deploy/docker-compose.yml" ]]; then
    echo "error: $LOCAL_DIR/deploy/docker-compose.yml not found" >&2
    exit 2
fi

echo "[deploy] target: $HOST:$REMOTE_DIR"

# Validate SSH reachability before shipping bytes.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "true" >/dev/null 2>&1; then
    echo "error: ssh $HOST failed (no passwordless access)" >&2
    exit 3
fi

ssh "$HOST" "mkdir -p '$REMOTE_DIR'"

# rsync: transfer source + deploy assets, exclude local venv/caches/lockfile
# (lockfile stays in-repo; sandbox is recreated per deploy via compose build).
rsync -az --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '*.egg-info/' \
    --exclude 'tests/' \
    --exclude 'knowledge/' \
    --exclude 'scripts/' \
    "$LOCAL_DIR/" "$HOST:$REMOTE_DIR/"

# Ship the knowledge/ package + seeder CLI into the remote dashboard/ dir
# so the Docker build context (which is `dashboard/`) can COPY them in.
# These are excluded from the main rsync above to keep --delete semantics
# scoped to the local dashboard/ tree.
rsync -az --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$REPO_ROOT/knowledge/" "$HOST:$REMOTE_DIR/knowledge/"

ssh "$HOST" "mkdir -p '$REMOTE_DIR/scripts'"
rsync -az \
    "$REPO_ROOT/scripts/__init__.py" \
    "$REPO_ROOT/scripts/seed_kb_from_memoria.py" \
    "$HOST:$REMOTE_DIR/scripts/"

echo "[deploy] rsync complete. building image on remote."
ssh "$HOST" "cd '$REMOTE_DIR/deploy' && sudo docker compose build --pull"

echo "[deploy] starting container."
ssh "$HOST" "cd '$REMOTE_DIR/deploy' && sudo docker compose up -d"

echo "[deploy] waiting for health."
for _ in $(seq 1 20); do
    if ssh "$HOST" "sudo docker exec devflow-dashboard python -c 'import urllib.request,sys; urllib.request.urlopen(\"http://127.0.0.1:8501/_stcore/health\", timeout=2).read()'" >/dev/null 2>&1; then
        echo "[deploy] OK — dashboard is serving (via npm_default network)"
        exit 0
    fi
    sleep 1
done

echo "error: dashboard did not become healthy within 20s" >&2
ssh "$HOST" "cd '$REMOTE_DIR/deploy' && sudo docker compose logs --tail=50 dashboard" >&2 || true
exit 4
