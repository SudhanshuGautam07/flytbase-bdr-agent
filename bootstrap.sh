#!/usr/bin/env bash
# ============================================================================
# BDR Intelligence Agent — one-command bootstrap
# Starts n8n (agent brain) + FastAPI (dashboard + evidence store), then
# imports/activates all 12 workflows and prints the dashboard URL.
#
# Requirements: node >= 18, python3, pip
# Keys: put your LLM/search keys in .env (see .env.example) BEFORE running.
# ============================================================================
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.npm-global/bin:$PATH"

echo "==> [1/6] Checking n8n"
if ! command -v n8n >/dev/null 2>&1; then
  npm config set prefix "$HOME/.npm-global" 2>/dev/null || true
  npm install -g n8n
fi
n8n --version || true

echo "==> [2/6] Checking Python deps (FastAPI)"
if [ ! -d "$ROOT/vendor/pydeps/fastapi" ]; then
  python3 -m pip install --quiet --target="$ROOT/vendor/pydeps" fastapi uvicorn
fi

echo "==> [3/6] Loading .env (API keys)"
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
else
  echo "   WARNING: no .env found. Copy .env.example to .env and add keys."
fi

echo "==> [4/6] Starting n8n on :5678"
export N8N_HOST=0.0.0.0
export N8N_PORT=5678
export N8N_TRUST_PROXY=1
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_DEFAULT_BINARY_DATA_MODE=filesystem
# CRITICAL for n8n 2.8.4 — env vars in expressions/Code are blocked unless 'false'
export N8N_BLOCK_ENV_ACCESS_IN_NODE=false
mkdir -p "$ROOT/data"
nohup n8n start > "$ROOT/data/n8n.log" 2>&1 &
N8N_PID=$!

echo "==> [5/6] Starting FastAPI dashboard on :8000"
PYTHONPATH="$ROOT/vendor/pydeps" nohup python3 "$ROOT/app/server.py" > "$ROOT/data/app.log" 2>&1 &
APP_PID=$!

echo "==> [6/6] Waiting for n8n, then importing 12 workflows"
for i in $(seq 1 45); do
  if curl -s http://127.0.0.1:5678/healthz >/dev/null 2>&1; then break; fi
  sleep 2
done
python3 "$ROOT/workflows/import_workflows.py"

echo
echo "============================================================"
echo "  BDR Intelligence Agent is running"
echo "  Dashboard : http://localhost:8000"
echo "  n8n       : http://localhost:5678  (user in .env)"
echo "  Trigger   : curl -X POST http://localhost:5678/webhook/master -d '{}' -H 'Content-Type: application/json'"
echo "  Or just click RUN AGENT in the dashboard."
echo "  Logs      : $ROOT/data/n8n.log  $ROOT/data/app.log"
echo "============================================================"
