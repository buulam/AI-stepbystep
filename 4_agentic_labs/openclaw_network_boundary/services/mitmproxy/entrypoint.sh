#!/usr/bin/env bash
# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# Starts mitmdump with the OTel addon, using the shared volume as confdir
# so the CA cert is written there on first run.

set -euo pipefail

CONFDIR="/home/mitmproxy/.mitmproxy"

log() { echo "[mitmproxy-entrypoint] $*"; }

log "Starting mitmdump on :8080 with OTel addon..."
log "CA cert will be written to ${CONFDIR}/mitmproxy-ca.pem on first run."

exec mitmdump \
  --listen-port 8080 \
  --set confdir="${CONFDIR}" \
  --scripts /addon/otel_addon.py
