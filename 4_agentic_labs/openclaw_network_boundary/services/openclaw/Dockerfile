# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# OpenClaw gateway container — node:22-slim + openclaw npm package.
# Outbound traffic is routed through mitmproxy via HTTP_PROXY/HTTPS_PROXY.

FROM node:22-slim

# Runtime dependencies: curl (health checks), bash, git (npm deps), gettext (envsubst), iptables (network isolation)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl bash git gettext-base ca-certificates iptables && \
    rm -rf /var/lib/apt/lists/*

# Write gitconfig directly so both insteadOf values land in the same section.
# npm forks git to clone SSH-pinned dependencies; this forces HTTPS without a key.
RUN printf '[url "https://github.com/"]\n\tinsteadOf = ssh://git@github.com/\n\tinsteadOf = git@github.com:\n' \
    > /root/.gitconfig && \
    npm install -g openclaw@latest

# Copy config template and entrypoint
COPY config/openclaw.json.template /etc/openclaw/openclaw.json.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Node compile cache for faster starts
ENV NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
RUN mkdir -p /var/tmp/openclaw-compile-cache

EXPOSE 19000

ENTRYPOINT ["/entrypoint.sh"]
