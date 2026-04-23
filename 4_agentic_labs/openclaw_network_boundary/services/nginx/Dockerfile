# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# nginx:1.30.0-otel ships with both ngx_otel_module and ngx_http_acme_module
# pre-installed as packages — no Rust toolchain or custom build required.

FROM nginx:1.30.0-otel

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
