# OpenClaw Network Boundary — Technical Reference

## Overview

A self-contained Docker Compose stack that wraps an OpenClaw AI gateway and an Ollama LLM backend inside a secure network envelope. All inbound HTTPS traffic is proxied and traced by nginx. All outbound traffic from OpenClaw is intercepted and decoded by mitmproxy. Both emit OpenTelemetry spans to a local collector that writes JSON Lines to a persistent volume.

---

## Architecture


```
Internet ──HTTPS──▶ nginx :OPENCLAW_HOST_PORT (TLS termination) ──▶ openclaw :19000
                         │
                   OTel inbound spans

openclaw ──iptables enforced──▶ mitmproxy :8080 ──▶ Internet
                                     │
                               OTel outbound spans
                                     │
                         otel-collector :4317
                                     │
                         /data/network-boundary-traffic.jsonl

openclaw ──────────────────────────────────────────────────────▶ ollama :11434
                        (net-internal, no external routing)
```

---

## Networks

| Network | Members | Notes |
|---|---|---|
| `net-internal` | openclaw, ollama | `internal: true` — LLM inference path only |
| `net-ingress` | nginx, openclaw | nginx exposes `OPENCLAW_HOST_PORT` |
| `net-proxy` | openclaw, mitmproxy | outbound proxy path |
| `net-telemetry` | nginx, mitmproxy, otel-collector | `internal: true` — OTel spans only |
| `net-pull` | ollama, nginx | internet access for model pulls and ACME challenges |

---

## Containers

### openclaw
- **Image**: custom build from `./services/openclaw`
- **Role**: AI gateway; handles browser pairing, token auth, and forwards LLM requests to Ollama
- **Auth**: `GATEWAY_TOKEN` env var — required for all API and UI access
- **Outbound proxy**: routes all HTTP/HTTPS via mitmproxy (`HTTP_PROXY`, `HTTPS_PROXY`)
- **CA trust**: mounts `mitm-certs` volume at `/certs`; `NODE_EXTRA_CA_CERTS=/certs/mitmproxy-ca.pem`
- **State**: `/root/.openclaw` persisted in `openclaw-state` volume (pairing data, config)
- **Exposes**: port `19000` to `net-ingress`

### ollama
- **Image**: custom build from `./services/ollama`
- **Role**: local LLM inference; serves the OpenAI-compatible API on port `11434`
- **Runtime**: `OLLAMA_RUNTIME` — `nvidia` for Jetson/NVIDIA GPU; empty for CPU/x86
- **Model pull**: pulls `OLLAMA_MODEL` on first start; stored in `ollama-models` volume
- **Tuning**: flash attention enabled; KV cache type `q8_0`; context length `32768`
- **Networks**: `net-internal` (openclaw access) + `net-pull` (model downloads)

### nginx
- **Image**: multi-stage build — builder compiles `ngx_http_acme_module.so` (Rust) against the exact nginx version; final stage is `nginx:1.27` + `nginx-module-otel` + acme module
- **TLS**: Let's Encrypt cert obtained and renewed natively by `ngx_http_acme_module` via HTTP-01 challenge; port 80 must be publicly reachable
- **Cert state**: `nginx-acme-state` named volume at `/var/cache/nginx/acme-letsencrypt/`; persists account key and cert across container restarts
- **Backend**: proxies to `openclaw:19000`
- **OTel**: `otel_exporter { endpoint otel-collector:4317; }` + `otel_trace on`
- **Span name**: `inbound.request`; attributes: `http.client_ip`, `http.method`, `http.path`, `http.status`
- **Startup**: renders nginx.conf from template, starts nginx; acme module issues cert on first request and handles all subsequent renewals in-process
- **Renewal**: fully in-process — module monitors expiry and renews without dropping connections or restarting nginx

### mitmproxy
- **Image**: custom `mitmproxy/mitmproxy:latest` + OTel SDK
- **CA cert**: auto-generated to `/home/mitmproxy/.mitmproxy/` on first run; shared via `mitm-certs` volume
- **Web UI**: port `8081` exposed on the host for live traffic inspection
- **OTel addon**: `otel_addon.py` emits `outbound.request` spans on every intercepted response; `outbound.tls_error` spans on certificate pinning failures
- **Span attributes**: `http.method`, `http.url`, `http.status_code`, `net.peer.name`, `net.peer.port`, `tls.version`, `http.response_time_ms`

### otel-collector
- **Image**: `otel/opentelemetry-collector-contrib:latest`
- **Receiver**: OTLP gRPC on `:4317`
- **Exporter**: file exporter → `/data/network-boundary-traffic.jsonl` with rotation (100 MB / 30 days)
- **User**: runs as root to write to the named Docker volume

---

## Volumes

| Volume | Purpose |
|---|---|
| `mitm-certs` | mitmproxy CA cert + key; shared read-only with openclaw |
| `otel-data` | `network-boundary-traffic.jsonl` — all spans from both sources |
| `nginx-acme-state` | nginx-acme module state (account key, cert, order data) at `/var/cache/nginx/acme-letsencrypt/` |
| `openclaw-state` | OpenClaw pairing data and runtime config (`/root/.openclaw`) |
| `ollama-models` | Downloaded Ollama model weights (`/data/models/ollama/models`) |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GATEWAY_TOKEN` | yes | — | Authentication token for OpenClaw UI and API |
| `OPENCLAW_USER` | no | (empty) | Optional username hint for OpenClaw |
| `OPENCLAW_HOST` | yes | — | IP or hostname of the Docker host (used in CORS origins) |
| `OPENCLAW_HOST_PORT` | no | `19000` | Host port nginx exposes for inbound HTTPS |
| `OLLAMA_MODEL` | no | `qwen2.5:3b` | Model pulled on first start and used by OpenClaw |
| `OLLAMA_CHAT_MODEL` | no | `qwen2.5:3b` | Chat model variant (can differ from OLLAMA_MODEL) |
| `OLLAMA_RUNTIME` | no | `nvidia` | Docker runtime — `nvidia` for Jetson/GPU, empty for CPU |
| `ACME_DOMAIN` | yes | — | Domain for Let's Encrypt certificate; must have DNS A record pointing to host |
| `ACME_EMAIL` | yes | — | Email for Let's Encrypt registration and expiry notices |

---

## TLS Termination

nginx terminates TLS on port `OPENCLAW_HOST_PORT` (default 19000). Certificates are issued and renewed by the [nginx-acme module](https://github.com/nginx/nginx-acme) (`ngx_http_acme_module`) running natively inside the nginx process. The module state (account key, cert, order data) is persisted in the `nginx-acme-state` Docker volume so container restarts do not re-issue unnecessarily.

**Port 80 must be publicly reachable** from the internet for the HTTP-01 challenge to succeed.

### Certificate flow

```
nginx (ngx_http_acme_module)
    │
    ├── HTTP-01 challenge: Let's Encrypt GETs /.well-known/acme-challenge/<token>
    │   via port 80 — module serves the response directly, no external tool needed
    │
    ├── On success: cert loaded into nginx memory ($acme_certificate variable)
    │
    └── State persisted at /var/cache/nginx/acme-letsencrypt/ (nginx-acme-state volume)
         ├── account key
         ├── certificate + chain
         └── order metadata
```

### Renewal

The module monitors certificate expiry in-process. When the cert approaches expiry it re-runs the HTTP-01 challenge and updates the in-memory certificate without restarting nginx or dropping connections. No cron jobs, external processes, or nginx reloads are required.

### DNS-01 alternative

If port 80 cannot be exposed, the acme.sh DNS-01 approach is documented in [docs/dns-acme.md](dns-acme.md). DNS-01 supports AWS Route53, Cloudflare, and Google Cloud DNS.

---

## OTel Span Reference

### `inbound.request` (nginx)
| Attribute | Value |
|---|---|
| `http.client_ip` | Client remote address |
| `http.method` | HTTP method |
| `http.path` | Request URI |
| `http.status` | Response status code |

### `outbound.request` (mitmproxy)
| Attribute | Value |
|---|---|
| `http.method` | HTTP method |
| `http.url` | Full URL |
| `http.status_code` | Response status code |
| `net.peer.name` | Destination hostname |
| `net.peer.port` | Destination port |
| `tls.version` | TLS version negotiated |
| `http.response_time_ms` | Round-trip time in ms |

### `outbound.tls_error` (mitmproxy)
| Attribute | Value |
|---|---|
| `tls.pinning_detected` | `true` |
| `net.peer.name` | Destination hostname |

---

## Usage

### Start the stack
```bash
cp .env.example .env
# fill in .env — at minimum: GATEWAY_TOKEN, OPENCLAW_HOST, ACME_DOMAIN, ACME_EMAIL
docker compose up -d
```

### View live traffic spans
```bash
docker exec otel-collector sh -c "tail -f /data/network-boundary-traffic.jsonl"
```

### Inspect outbound traffic in the mitmproxy web UI
```
http://<host>:8081
```

### Check status
```bash
docker compose ps
```