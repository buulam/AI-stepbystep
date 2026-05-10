# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# Multi-arch Ollama binary build.
# arm64 (Jetson/JetPack 6): base arm64 binary + CUDA jetpack6 libs from official release.
# amd64 (x86): standard amd64 binary from official release.
# Set OLLAMA_RUNTIME=nvidia in .env for Jetson; leave empty for x86.

FROM ubuntu:22.04

ARG OLLAMA_VERSION=v0.21.0
ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates zstd tar bash && \
    rm -rf /var/lib/apt/lists/*

RUN if [ "$TARGETARCH" = "arm64" ]; then \
      curl -fsSL https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-arm64.tar.zst \
        | zstd -d | tar -x -C /usr && \
      curl -fsSL https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-arm64-jetpack6.tar.zst \
        | zstd -d | tar -x -C /usr; \
    else \
      curl -fsSL https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst \
        | zstd -d | tar -x -C /usr; \
    fi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV OLLAMA_MODELS=/data/models/ollama/models
ENV PATH="/usr/bin:${PATH}"
# nvidia-container-runtime requires these to inject GPU devices
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

EXPOSE 11434

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
