#!/usr/bin/env bash
# Start n8n with env vars loaded from .env + the flag that unblocks $env / getEnv.
set -a
source /home/user/flytbase-bdr-agent/.env
set +a
export PATH="$HOME/.npm-global/bin:$PATH"
export N8N_HOST=0.0.0.0
export N8N_PORT=5678
export N8N_TRUST_PROXY=1
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_DEFAULT_BINARY_DATA_MODE=filesystem
# CRITICAL for n8n 2.8.4: env vars are blocked in expressions/Code unless this is 'false'
export N8N_BLOCK_ENV_ACCESS_IN_NODE=false
exec n8n start
