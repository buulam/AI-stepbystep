# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# Multi-stage build:
#   builder — installs nginx-module-otel (which upgrades nginx to its mainline
#             version), detects the resulting nginx version, downloads matching
#             nginx source, then compiles ngx_http_acme_module.so against it.
#             ABI is guaranteed to match the final image because both go through
#             the same apt upgrade path.
#   final   — clean nginx:1.27 + ngx_otel_module + the compiled acme module.
#             No Rust toolchain, no build deps in the final image.

# ── Stage 1: build nginx-acme ─────────────────────────────────────────────────
FROM nginx:1.27 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpcre2-dev \
    zlib1g-dev \
    libssl-dev \
    libclang-dev \
    pkg-config \
    curl \
    ca-certificates \
    git \
    gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain — nginx-acme is written in Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --no-modify-path
ENV PATH="/root/.cargo/bin:${PATH}"

# Install nginx-module-otel from the nginx mainline apt repo.
# This upgrades nginx to the same version the final stage will run, so the
# source tree we compile nginx-acme against is guaranteed to match.
RUN curl -fsSL https://nginx.org/keys/nginx_signing.key \
        | gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
https://nginx.org/packages/mainline/debian bookworm nginx" \
        > /etc/apt/sources.list.d/nginx.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nginx-module-otel && \
    rm -rf /var/lib/apt/lists/* /etc/apt/sources.list.d/nginx.list

# Detect the actual post-upgrade nginx version, download matching source,
# and configure it for compat dynamic-module builds.
RUN set -eux; \
    VER=$(nginx -v 2>&1 | sed 's|nginx version: nginx/||'); \
    echo "Building nginx-acme against nginx ${VER}"; \
    curl -fsSL "https://nginx.org/download/nginx-${VER}.tar.gz" | \
        tar -xz -C /usr/src; \
    cd "/usr/src/nginx-${VER}"; \
    ./configure --with-compat --with-http_ssl_module; \
    echo "${VER}" > /NGINX_VERSION

# Build nginx-acme against the configured source tree
RUN git clone --depth=1 https://github.com/nginx/nginx-acme.git /usr/src/nginx-acme
WORKDIR /usr/src/nginx-acme
RUN set -eux; \
    VER=$(cat /NGINX_VERSION); \
    NGINX_BUILD_DIR="/usr/src/nginx-${VER}/objs" \
    cargo build --release

# ── Stage 2: final image ──────────────────────────────────────────────────────
FROM nginx:1.27

RUN set -eux && \
    apt-get update && \
    apt-get install -y --no-install-recommends gnupg2 curl gettext-base && \
    # ngx_otel_module from nginx mainline repo (also upgrades nginx binary)
    curl -fsSL https://nginx.org/keys/nginx_signing.key \
        | gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
https://nginx.org/packages/mainline/debian bookworm nginx" \
        > /etc/apt/sources.list.d/nginx.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nginx-module-otel && \
    apt-get remove -y gnupg2 && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /etc/apt/sources.list.d/nginx.list && \
    mkdir -p /var/cache/nginx/acme-letsencrypt

# Copy the compiled nginx-acme module from the builder stage
COPY --from=builder /usr/src/nginx-acme/target/release/libnginx_acme.so \
    /etc/nginx/modules/ngx_http_acme_module.so

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
