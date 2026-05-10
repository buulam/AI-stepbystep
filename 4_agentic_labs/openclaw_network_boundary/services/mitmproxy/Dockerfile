# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# mitmproxy with OTel Python addon dependencies

FROM mitmproxy/mitmproxy:latest

# Install OTel SDK and gRPC exporter into the embedded Python environment
COPY requirements.txt /addon/requirements.txt
RUN pip install --no-cache-dir -r /addon/requirements.txt

# Copy addon and entrypoint
COPY otel_addon.py /addon/otel_addon.py
COPY entrypoint.sh /entrypoint.sh

USER root
RUN chmod +x /entrypoint.sh

USER mitmproxy
ENTRYPOINT ["/entrypoint.sh"]
