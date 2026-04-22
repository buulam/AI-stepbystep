# OpenClaw Network Boundary

A complete, self-contained Docker Compose stack that runs [OpenClaw](https://openclaw.ai/) inside a secure network boundary: automatic TLS termination, kernel-level outbound traffic isolation via mitmproxy, and OpenTelemetry observability for every request in and every call out.

## The core idea

**Containment first.** OpenClaw runs in a container with no direct internet access. iptables OUTPUT rules enforced at the kernel level prevent any process inside the container from bypassing the proxy — even if the application-layer `HTTP_PROXY` env vars were ignored. All outbound traffic is forced through mitmproxy, which decrypts, records, and re-encrypts every HTTPS connection the agent makes. Nothing leaves unobserved.

**nginx as the public entry point.** nginx sits in front of OpenClaw as the sole inbound path. The gateway is never exposed directly. Everything that makes securing an OpenClaw deployment hard — access control, TLS certificates, routing — gets solved at the nginx layer, leaving OpenClaw's internals untouched.

**Certificates handled natively.** nginx uses the [nginx-acme module](https://github.com/nginx/nginx-acme) to obtain and renew a Let's Encrypt certificate automatically via HTTP-01 challenge. No external tools, no credential management, no renewal cron jobs — the module handles the full certificate lifecycle inside the nginx process.

**Full observability.** Both nginx (inbound) and mitmproxy (outbound) emit OpenTelemetry spans to a local collector. Every request in and every call out is recorded with method, URL, status, and timing. The result is a complete audit trail of what the agent did and what it said to whom.

**First control, next shape the traffic.** We collect OTel with the intent of analyzing calls that matter and configuring both the nginx ingress and mitmproxy egress (and iptables) in a way that will allow OpenClaw to do **ONLY** what we allow it to. No more worrying about what it does. We force it to play by the rules.

---

## Goals

By the end of this lab, you will have:

- OpenClaw running behind a network boundary with kernel-level outbound isolation
- Ollama serving a local LLM that OpenClaw uses for inference
- A valid Let's Encrypt TLS certificate issued and renewed automatically by nginx
- All outbound traffic from OpenClaw intercepted and decoded by mitmproxy
- OpenTelemetry spans for both inbound and outbound traffic written to a local JSON Lines file

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

## Exposing nginx to the internet

The nginx-acme module obtains your TLS certificate using the **HTTP-01 challenge** — Let's Encrypt sends an HTTP request to port 80 on your domain to prove you control it. This means **port 80 on your host must be publicly reachable from the internet** before you start the stack.

Here are the three common home lab setups:

### Option A — Direct hosting (public IP on the host)

```
Internet ──port 80/443──▶ Your host (public IP)
```

Your machine has a public IP address assigned directly to its network interface (common with cloud VMs, dedicated servers, or some ISPs). No router configuration needed — just confirm your host firewall allows inbound port 80.

```bash
# Test from a device outside your network (phone on mobile data, etc.):
curl http://<your-public-ip>/
```

### Option B — Port forwarding (host behind a home router)

```
Internet ──port 80──▶ Router (public IP) ──NAT──▶ Your host (LAN IP, e.g. 192.168.1.x)
```

Most home labs sit behind a NAT router. You need to forward port 80 (and your OPENCLAW_HOST_PORT, default 19000) from the router's public IP to your host's LAN IP.

1. **Assign your host a static LAN IP** — in your router's DHCP settings, create a reservation using the host's MAC address. This prevents the LAN IP from changing after a reboot.
2. **Create a port forwarding rule** — in your router's admin UI (usually `192.168.1.1` or `192.168.0.1`), add:
   - External port `80` → Internal IP `<host-LAN-ip>` port `80`
   - External port `19000` (or your `OPENCLAW_HOST_PORT`) → Internal IP `<host-LAN-ip>` same port
3. **Set `ACME_DOMAIN`** to a DNS name pointing at your router's public IP (see dynamic DNS below).

> **ISP port blocking:** Some ISPs block inbound port 80 on residential connections. Test with `curl http://<your-public-ip>/` from outside your network. If it times out and port forwarding is correctly configured, your ISP may be blocking it. Contact them or consider a DNS-01 validation alternative (see [docs/dns-acme.md](docs/dns-acme.md)).

### Option C — DMZ (host in router's DMZ)

```
Internet ──all ports──▶ Router ──DMZ──▶ Your host (receives all inbound traffic)
```

Many routers support a DMZ setting that forwards all inbound traffic to a single host. This is the easiest configuration — no per-port rules — but it exposes every port on that machine directly. Use this only on a dedicated lab machine that runs nothing sensitive.

In your router's admin UI, find the DMZ or "exposed host" setting and enter your host's LAN IP.

### Dynamic DNS (no static public IP)

If your ISP assigns a dynamic public IP, you need a DNS name that updates automatically when the IP changes. Free options include [DuckDNS](https://www.duckdns.org/) and [No-IP](https://www.noip.com/). Both provide a small client that runs on your host and updates the DNS record when your IP changes. Set `ACME_DOMAIN` to this dynamic hostname.

---

## Prerequisites

1. A Linux host (or VM) with:
   - Docker Engine 24+ and Docker Compose v2 (`docker compose` — not the legacy `docker-compose`)
   - Git
   - Recommended: An NVIDIA GPU + NVIDIA Container Toolkit (tested on as little as 4 GB RAM on a GTX 1650 Super) or a Jetson with JetPack 6 and the NVIDIA Container Runtime (tested on a Jetson Orin Nano with 8 GB shared memory)
   - CPU-only is possible but inference speed will be in the single-digit tokens-per-second range
2. A domain name with its DNS A record pointing to your host's public IP
3. **Port 80 on your host publicly reachable from the internet** (see [Exposing nginx to the internet](#exposing-nginx-to-the-internet) above)
4. Port `443` or your chosen `OPENCLAW_HOST_PORT` open on the host firewall for inbound HTTPS

> **DNS-01 alternative:** If you cannot expose port 80, see [docs/dns-acme.md](docs/dns-acme.md) for the acme.sh DNS-01 approach that works without any inbound port 80 access.

---

## Step 1: Verify Docker Compose

**Do this:**

```bash
docker compose version
```

**What you'll see:**

```
Docker Compose version v2.x.x
```

![Docker Compose version check](./images/step-1-docker.png)

**Why it matters:** The stack uses Docker Compose v2 syntax (`docker compose`, not `docker-compose`). If you see `command not found` or a v1 version, update before continuing:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

---

## Step 2: Clone the repository and navigate to the lab

**Do this:**

```bash
git clone https://github.com/f5devcentral/AI-stepbystep.git
cd AI-stepbystep/4_agentic_labs/openclaw_network_boundary
```

**What you'll see:** The lab directory with `compose.yml`, `services/`, and `.env.example`.

**Why it matters:** Everything in this lab runs from this directory. All `docker compose` commands assume you're here.

---

## Step 3: Configure your environment

**Do this:**

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```bash
# Jetson (arm64 + NVIDIA GPU): nvidia  |  x86 (no NVIDIA Container Toolkit): leave empty
OLLAMA_RUNTIME=

# Token required to log in to the OpenClaw UI
GATEWAY_TOKEN=replace-with-a-secure-random-token

# Ollama model to pull on first start
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_CHAT_MODEL=qwen2.5:3b

# IP address or hostname of the machine running Docker (used for CORS)
OPENCLAW_HOST=192.168.1.100
OPENCLAW_HOST_PORT=19000

# Your publicly accessible domain and email for Let's Encrypt
ACME_DOMAIN=openclaw.example.com
ACME_EMAIL=admin@example.com
```

**What you'll see:** A filled-in `.env` file with no placeholder values remaining.

**Why it matters:** `ACME_DOMAIN` must match the DNS A record you've already pointed at your host. Let's Encrypt will connect to this domain on port 80 to issue the certificate — if the DNS isn't set up correctly the cert issuance will fail and nginx won't start.

> **Never commit `.env` to git.** It is already listed in `.gitignore`.

---

## Step 4: Start the stack

**Do this:**

```bash
docker compose up -d --build
```

**What you'll see:**

Docker builds five container images on first run. The nginx image compiles the nginx-acme Rust module against the nginx source — this takes **3–5 minutes** on first build. Subsequent starts use the cached image and are fast.

```
[+] Building ...
 => [nginx builder] cargo build --release          180s
 => [nginx] COPY --from=builder libnginx_acme.so    0s
[+] Running 5/5
 ✔ Container otel-collector  Started
 ✔ Container ollama          Started
 ✔ Container mitmproxy       Started
 ✔ Container openclaw        Started
 ✔ Container nginx           Started
```

Watch Ollama pull the model (5–15 minutes depending on model size and network):

```bash
docker compose logs -f ollama
```

![Docker Ollama](./images/step-4-ollama.png)

Watch OpenClaw become ready:

```bash
docker compose logs -f openclaw
```

![Docker OpenClaw](./images/step-4-openclaw.png)

**Why it matters:** The first build is the slow part. Once the images are cached, `docker compose up -d` on subsequent starts takes under 10 seconds.

---

## Step 5: Watch the TLS certificate being issued

**Do this:**

```bash
docker compose logs -f nginx
```

**What you'll see:**

First, nginx renders its config and starts:

```
nginx  | [nginx-acme-module] Rendering nginx.conf (domain=openclaw.example.com backend=openclaw:19000)...
nginx  | [nginx-acme-module] Starting nginx (acme module handles cert issuance and renewal)...
```

Within seconds, Let's Encrypt validation servers hit port 80 on your domain — you'll see their requests in the log:

```
nginx  | 23.178.112.213 - - [22/Apr/2026:15:38:31 +0000] "GET /.well-known/acme-challenge/VJBHPwtWNA... HTTP/1.1" 200 87 "-" "Mozilla/5.0 (compatible; Let's Encrypt validation server...)"
nginx  | 3.129.206.157  - - [22/Apr/2026:15:38:31 +0000] "GET /.well-known/acme-challenge/VJBHPwtWNA... HTTP/1.1" 200 87 ...
```

After the challenge succeeds, nginx loads the certificate and your HTTPS endpoint is live.

**Why it matters:** Those `200` responses from Let's Encrypt's IPs confirm that port 80 is publicly reachable and the HTTP-01 challenge succeeded. If you see `connection refused` or the log stalls here, port 80 isn't reachable — revisit the [network setup](#exposing-nginx-to-the-internet) section.

---

## Step 6: Verify the stack is healthy

**Do this:**

```bash
docker compose ps
```

**What you'll see:**

```
NAME             STATUS
nginx            Up X minutes
openclaw         Up X minutes
mitmproxy        Up X minutes
otel-collector   Up X minutes
ollama           Up X minutes
```

![Docker Compose ps](./images/step-5-docker-compose.png)

**Why it matters:** All five containers must be `Up`. If any shows `Exited`, inspect its logs:

```bash
docker compose logs <container-name>
```

---

## Step 7: Open OpenClaw in your browser

**Do this:**

Navigate to:

```
https://<ACME_DOMAIN>:<OPENCLAW_HOST_PORT>
```

When prompted for a token, enter the value you set for `GATEWAY_TOKEN` in `.env`.

**What you'll see:** The response `pairing required` — this confirms nginx is proxying to OpenClaw and TLS is working with a valid certificate.

![Pairing Required](./images/step-6-1-openclaw-browser.png)

**Why it matters:** A valid TLS certificate from Let's Encrypt means your browser won't show a security warning. If you see a certificate error, the cert may still be issuing — wait 30 seconds and reload.

Now pair a device. On your Docker host, list pending pairing requests:

```bash
docker exec -e GATEWAY_TOKEN=$GATEWAY_TOKEN openclaw openclaw devices list
```

![List Pairing Requests](./images/step-6-2-openclaw-pairing-list.png)

Copy the request ID and approve it:

```bash
docker exec -e GATEWAY_TOKEN=$GATEWAY_TOKEN openclaw openclaw devices approve <request-id>
```

![Approve Pairing Request](./images/step-6-3-openclaw-pairing-approve.png)

Return to the browser — you should now see the OpenClaw chat interface.

![It works!](./images/step-6-4-openclaw-works.png)

**Why it matters:** OpenClaw is now running behind the network boundary — all outbound calls it makes are intercepted by mitmproxy and recorded as OTel spans.

---

## Step 8: Inspect outbound traffic through mitmproxy

**Do this:**

```bash
docker logs -f mitmproxy
```

**What you'll see:**

```
[otel-addon] outbound.request POST https://api.example.com/v1/chat 200 412ms
```

![mitmproxy log output](./images/step-7-mitm-example.png)

To explore traffic interactively in the mitmproxy web UI, expose its interface temporarily:

```bash
docker exec -it mitmproxy mitmweb --web-host 0.0.0.0 --web-port 8081 --mode regular@8082
```

Then open `http://<host-ip>:8081` in a browser.

![mitmproxy web launch](./images/step-7-mitm-expose.png)

![mitmproxy web UI](./images/step-7-mitm-web.png)

**Why it matters:** Every HTTPS call OpenClaw makes — to LLM APIs, external services, anything — is decrypted and logged here. This is your first view into what the agent is actually doing on the network.

> **Only expose the mitmproxy web UI in a secured lab environment.** Flows captured by the running mitmdump will not appear in this UI — it is a separate proxy instance useful for interactive inspection only.

---

## Step 9: View OpenTelemetry spans

**Do this:**

```bash
docker cp otel-collector:/data/network-boundary-traffic.jsonl /tmp/spans.jsonl && tail -f /tmp/spans.jsonl
```

**What you'll see:**

Inbound requests from nginx:

```json
{"name":"inbound.request","attributes":{"http.client_ip":"203.0.113.5","http.method":"GET","http.path":"/chat","http.status":"200"}}
```

Outbound requests intercepted by mitmproxy:

```json
{"name":"outbound.request","attributes":{"http.method":"POST","http.url":"https://api.example.com/v1/chat","http.status_code":200,"net.peer.name":"api.example.com","tls.version":"TLSv1.3","http.response_time_ms":412}}
```

If OpenClaw encounters a service with certificate pinning:

```json
{"name":"outbound.tls_error","attributes":{"tls.pinning_detected":true,"net.peer.name":"pinned-service.example.com"}}
```

**Why it matters:** The JSON Lines file is a durable, structured audit trail of everything that happened — who called OpenClaw (inbound) and who OpenClaw called (outbound). You now have the raw material to write allow/deny policies or alert on unexpected destinations.

---

## Step 10: Verify network isolation

**Do this:**

```bash
docker logs openclaw | grep iptables
```

**What you'll see:**

```
[openclaw-entrypoint] iptables OUTPUT policy set: RFC1918 allowed, public internet blocked.
```

![iptables isolation confirmation](./images/step-9-iptables.png)

**Why it matters:** This confirms the kernel-level firewall is active inside the openclaw container. Any direct outbound internet connection that bypasses mitmproxy is dropped at the kernel — not just blocked at the application layer. Even if OpenClaw ignored the `HTTP_PROXY` env var, it could not reach the internet directly.

---

## Step 11: Certificate auto-renewal

**Why it matters:** The nginx-acme module handles renewal entirely inside the nginx process — no cron jobs, no external tools, no container restarts needed. When a certificate is within 30 days of expiry the module renews it automatically, updates the in-memory certificate, and continues serving without dropping connections.

To confirm the module is managing the cert:

```bash
docker compose logs nginx | grep -i acme
```

You should see the initial issuance lines. The module logs renewal activity to nginx's error log as it approaches expiry.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| nginx exits immediately on start | Run `docker compose logs nginx` — likely a config render error; check that all env vars in `.env` are set |
| `module version X instead of Y` error | The nginx-acme module was compiled against a different nginx version than is installed. Rebuild with `docker compose build --no-cache nginx` |
| HTTP-01 challenge fails / cert not issued | Port 80 must be publicly reachable. Test with `curl http://<ACME_DOMAIN>/` from outside your network. Check firewall, port forwarding, and ISP blocking |
| IPv6 `Network is unreachable` in logs | Harmless — the host has no IPv6. The `ipv6=off` resolver option suppresses this |
| Browser shows certificate error | Cert may still be issuing — wait 30 seconds and reload. Check `docker compose logs nginx` for challenge 200 responses |
| nginx starts but browser shows `connection refused` | Confirm `OPENCLAW_HOST_PORT` is open on the host firewall and nginx is `Up` |
| OpenClaw UI loads but model doesn't respond | Check `docker compose logs ollama` — model may still be pulling |
| Ollama fails on x86 (`unknown runtime`) | Set `OLLAMA_RUNTIME=` (empty) in `.env` |
| Ollama running on CPU instead of GPU | Ensure `OLLAMA_RUNTIME=nvidia` and NVIDIA Container Toolkit is installed |
| iptables isolation warning in openclaw logs | Ensure `cap_add: NET_ADMIN` is present in the compose service definition |
| No outbound spans in OTel file | Confirm openclaw is proxying through mitmproxy (`docker logs openclaw`) |
| TLS errors in openclaw outbound logs | Verify `NODE_EXTRA_CA_CERTS` is set and `mitm-certs` volume is mounted |

---

## DNS-01 alternative

If you cannot expose port 80 to the internet, see **[docs/dns-acme.md](docs/dns-acme.md)** for step-by-step instructions to switch to the acme.sh DNS-01 approach. DNS-01 supports AWS Route53, Cloudflare, and Google Cloud DNS with no inbound port requirements.

---

## Cleaning up

Stop and remove the stack:

```bash
docker compose down
```

To also remove the named volumes (certificates, model weights, OpenClaw state, traffic logs):

```bash
docker compose down -v
```

> Removing volumes deletes the TLS certificate state and all downloaded model weights. The next `docker compose up` will re-download the model and request a new certificate.

> **Let's Encrypt rate-limits to 5 duplicate certificates per week per domain — avoid unnecessary teardowns.**

---

## Next steps

- Forward spans to a backend like Jaeger, Tempo, or an OTLP-compatible SaaS by modifying `services/otel/collector.yaml`
- Use the `outbound.tls_error` spans to identify which external services use certificate pinning
- Tighten the mitmproxy ruleset to block categories of outbound calls entirely
- Switch to DNS-01 validation (no public port 80 required): [docs/dns-acme.md](docs/dns-acme.md)
- Review the full technical reference: [docs/technical.md](docs/technical.md)

## License

Apache 2.0 — Copyright (c) 2026 markosluga
