#!/bin/sh
# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# 1. Render nginx.conf from template
# 2. Start nginx
#
# Certificate issuance and renewal are handled natively by the
# nginx-acme module (ngx_http_acme_module) — no external tooling needed.

set -e

: "${ACME_DOMAIN:?ACME_DOMAIN must be set}"
: "${ACME_EMAIL:?ACME_EMAIL must be set}"

log() { echo "[nginx-acme-module] $*"; }

mkdir -p /var/cache/nginx/acme-letsencrypt

log "Rendering nginx.conf (domain=${ACME_DOMAIN} backend=${BACKEND_HOST}:${BACKEND_PORT})..."
envsubst '$BACKEND_HOST $BACKEND_PORT $ACME_DOMAIN $ACME_EMAIL' \
    < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

log "Starting nginx (acme module handles cert issuance and renewal)..."
exec nginx -g "daemon off;"
