#!/usr/bin/env bash
# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# Starts ollama serve, waits for readiness, then pulls the configured model
# if it is not already present in the volume.

set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen3.5:2b}"

log() { echo "[ollama-entrypoint] $*"; }

# Start the ollama server in the background
log "Starting ollama serve..."
ollama serve &
SERVE_PID=$!

# Wait until the API is accepting connections
log "Waiting for ollama to be ready..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
  sleep 2
done
log "Ollama is ready."

# Pull the model only if it is not already present
if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
  log "Model '${MODEL}' already present — skipping pull."
else
  log "Pulling model '${MODEL}'..."
  ollama pull "${MODEL}"
  log "Model '${MODEL}' pulled successfully."
fi

# Keep the container alive by waiting on the server process
wait "${SERVE_PID}"
