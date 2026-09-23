#!/usr/bin/env bash
set -euo pipefail

export N8N_USER_FOLDER="${N8N_USER_FOLDER:-/var/data/n8n}"
export DATA_DIR="${DATA_DIR:-/var/data/bdr}"
export N8N_HOST="${N8N_HOST:-127.0.0.1}"
export N8N_PORT="${N8N_PORT:-5678}"
export N8N_PROTOCOL="http"
export N8N_BLOCK_ENV_ACCESS_IN_NODE="false"
export N8N_RUNNERS_ENABLED="false"
export N8N_DIAGNOSTICS_ENABLED="false"
export N8N_PERSONALIZATION_ENABLED="false"
export N8N_SECURE_COOKIE="false"
export N8N_DEFAULT_BINARY_DATA_MODE="filesystem"

mkdir -p "$N8N_USER_FOLDER" "$DATA_DIR"

# Generate fixed-ID workflows, import idempotently, then publish each workflow.
python3 /app/workflows/prepare_render_workflows.py
n8n import:workflow --separate --input=/app/render_workflows
for workflow_id in \
  TSRCH00000000001 TFETCH0000000002 TLLM000000000003 \
  A1ICP00000000001 A2DISC0000000001 A3VERI0000000001 A4CONT0000000001 \
  A5CVER0000000001 A6RSCH0000000001 A7MAIL0000000001 A8FACT0000000001 \
  MASTER0000000001; do
  n8n publish:workflow --id="$workflow_id"
done
# CLI import/publish creates versions but may leave trigger workflows inactive in n8n 2.x.
# Set active atomically while n8n is stopped, then start n8n so it registers webhooks.
python3 /app/workflows/activate_render_db.py

# n8n is private inside the container; only FastAPI binds Render's public PORT.
n8n start &
N8N_PID=$!

cleanup() {
  kill "$N8N_PID" 2>/dev/null || true
  wait "$N8N_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${N8N_PORT}/healthz" >/dev/null 2>&1; then
    echo "n8n is ready"
    break
  fi
  if ! kill -0 "$N8N_PID" 2>/dev/null; then
    echo "n8n exited during startup" >&2
    exit 1
  fi
  sleep 2
done

exec uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1
