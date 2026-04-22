# DNS-01 Certificate Validation (acme.sh alternative)

The default design uses the nginx-acme module with **HTTP-01** validation — Let's Encrypt connects to port 80 on your domain to prove ownership. This is the simplest option and requires no DNS provider credentials.

If you cannot expose port 80 to the internet, you can switch to **DNS-01** validation using [acme.sh](https://github.com/acmesh-official/acme.sh) embedded in the nginx container. DNS-01 creates a temporary TXT record in your DNS zone to prove ownership — port 80 never needs to be reachable.

## When to use DNS-01

- Your ISP blocks inbound port 80
- Your firewall policy does not allow port 80 from the internet
- You want a wildcard certificate (`*.yourdomain.com`)
- You are running the stack on an internal network with no public HTTP access

DNS-01 also renews certificates without any downtime — no port 80 is touched during renewal.

---

## Supported DNS providers

| Provider | `ACME_METHOD` value | Credentials needed |
|---|---|---|
| **AWS Route53** | `dns-route53` | IAM key + secret with Route53 permissions (see below) |
| **Cloudflare** | `dns-cloudflare` | API token with Zone / DNS / Edit permission |
| **Google Cloud DNS** | `dns-google` | Service account JSON with `roles/dns.admin` |

### AWS Route53 IAM policy

The IAM user needs these permissions scoped to the hosted zone for your domain:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:GetChange",
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "route53:ChangeResourceRecordSets",
      "Resource": "arn:aws:route53:::hostedzone/<YOUR_ZONE_ID>"
    }
  ]
}
```

---

## How to switch to DNS-01

You need to replace four files in `services/nginx/` and update your `.env`. No other containers change.

### 1. Replace `services/nginx/Dockerfile`

Replace the multi-stage nginx-acme build with the original single-stage build that embeds acme.sh:

```dockerfile
# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0

FROM nginx:1.27

RUN set -eux && \
    apt-get update && \
    apt-get install -y --no-install-recommends gnupg2 curl socat gettext-base && \
    # nginx OTel module from mainline repo
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
    # Install acme.sh
    mkdir -p /root/.acme.sh && \
    curl -fsSL https://github.com/acmesh-official/acme.sh/archive/master.tar.gz \
        | tar -xz -C /root/.acme.sh --strip-components=1 && \
    chmod +x /root/.acme.sh/acme.sh && \
    mkdir -p /etc/nginx/certs

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

### 2. Replace `services/nginx/entrypoint.sh`

```sh
#!/bin/sh
# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0

set -e

: "${ACME_DOMAIN:?ACME_DOMAIN must be set}"
: "${ACME_EMAIL:?ACME_EMAIL must be set}"

ACME_METHOD="${ACME_METHOD:-dns-route53}"
CERT_DIR="/etc/nginx/certs"
ACME_HOME="${CERT_DIR}/.acme.sh"
ACME="/root/.acme.sh/acme.sh --home ${ACME_HOME}"

log() { echo "[nginx-acme] $*"; }

mkdir -p "${CERT_DIR}" "${ACME_HOME}"

case "${ACME_METHOD}" in
  dns-route53)
    : "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID must be set for dns-route53}"
    : "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY must be set for dns-route53}"
    ISSUE_FLAGS="--dns dns_aws"
    log "Using DNS-01 via AWS Route53"
    ;;
  dns-cloudflare)
    : "${CLOUDFLARE_DNS_API_TOKEN:?CLOUDFLARE_DNS_API_TOKEN must be set for dns-cloudflare}"
    export CF_Token="${CLOUDFLARE_DNS_API_TOKEN}"
    ISSUE_FLAGS="--dns dns_cf"
    log "Using DNS-01 via Cloudflare"
    ;;
  dns-google)
    : "${GOOGLE_APPLICATION_CREDENTIALS_JSON:?GOOGLE_APPLICATION_CREDENTIALS_JSON must be set for dns-google}"
    mkdir -p /run/acme
    printf '%s' "${GOOGLE_APPLICATION_CREDENTIALS_JSON}" > /run/acme/gcp-creds.json
    chmod 600 /run/acme/gcp-creds.json
    export GCE_SERVICE_ACCOUNT_FILE=/run/acme/gcp-creds.json
    ISSUE_FLAGS="--dns dns_gcloud"
    log "Using DNS-01 via Google Cloud DNS"
    ;;
  http)
    ISSUE_FLAGS="--standalone --httpport 80"
    log "Using HTTP-01 standalone — port 80 must be reachable from the internet"
    ;;
  *)
    log "ERROR: Unknown ACME_METHOD '${ACME_METHOD}'."
    exit 1
    ;;
esac

log "Registering ACME account for ${ACME_EMAIL}..."
$ACME --register-account -m "${ACME_EMAIL}" --server letsencrypt 2>/dev/null || true

log "Issuing cert for ${ACME_DOMAIN}..."
until
  $ACME --issue ${ISSUE_FLAGS} -d "${ACME_DOMAIN}" --server letsencrypt && \
  $ACME --install-cert -d "${ACME_DOMAIN}" \
    --cert-file      "${CERT_DIR}/cert.pem" \
    --key-file       "${CERT_DIR}/privkey.pem" \
    --fullchain-file "${CERT_DIR}/fullchain.pem"
do
  log "Cert issuance/install failed — retrying in 5 min..."
  sleep 300
done
log "Cert installed to ${CERT_DIR}."

log "Rendering nginx.conf..."
envsubst '$BACKEND_HOST $BACKEND_PORT' \
    < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# 12 h renewal loop in background
(while true; do
  sleep 43200
  log "Running renewal check..."
  if [ "${ACME_METHOD}" = "http" ]; then
    nginx -s quit 2>/dev/null || true
    sleep 3
  fi
  $ACME --renew ${ISSUE_FLAGS} -d "${ACME_DOMAIN}" --server letsencrypt || true
  $ACME --install-cert -d "${ACME_DOMAIN}" \
    --cert-file      "${CERT_DIR}/cert.pem" \
    --key-file       "${CERT_DIR}/privkey.pem" \
    --fullchain-file "${CERT_DIR}/fullchain.pem" \
    --reloadcmd      "nginx -s reload" \
    || log "WARNING: cert install/reload failed"
  if [ "${ACME_METHOD}" = "http" ]; then
    nginx -g "daemon off;" &
  fi
  log "Renewal check done."
done) &

log "Starting nginx..."
exec nginx -g "daemon off;"
```

### 3. Replace `services/nginx/nginx.conf.template`

```nginx
load_module modules/ngx_otel_module.so;

events {
    worker_connections 1024;
}

http {
    otel_exporter {
        endpoint otel-collector:4317;
    }

    access_log /dev/stdout;
    error_log  /dev/stderr warn;

    upstream backend {
        server ${BACKEND_HOST}:${BACKEND_PORT};
        keepalive 32;
    }

    server {
        listen 19000 ssl;
        server_name _;

        ssl_certificate     /etc/nginx/certs/fullchain.pem;
        ssl_certificate_key /etc/nginx/certs/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 10m;

        otel_trace         on;
        otel_trace_context propagate;
        otel_span_name     "inbound.request";

        location / {
            proxy_pass         http://backend;
            proxy_http_version 1.1;
            proxy_set_header   Upgrade         $http_upgrade;
            proxy_set_header   Connection      "upgrade";
            proxy_set_header   Host            $host;
            proxy_set_header   X-Real-IP       $remote_addr;
            proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;

            otel_span_attr http.client_ip  $remote_addr;
            otel_span_attr http.method     $request_method;
            otel_span_attr http.path       $request_uri;
            otel_span_attr http.status     $status;
        }
    }
}
```

### 4. Update `compose.yml` — nginx service

Replace the nginx service environment block with:

```yaml
environment:
  ACME_DOMAIN: ${ACME_DOMAIN}
  ACME_EMAIL: ${ACME_EMAIL}
  ACME_METHOD: ${ACME_METHOD:-dns-route53}
  BACKEND_HOST: openclaw
  BACKEND_PORT: "19000"
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
  CLOUDFLARE_DNS_API_TOKEN: ${CLOUDFLARE_DNS_API_TOKEN:-}
  GOOGLE_APPLICATION_CREDENTIALS_JSON: ${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}
```

Replace the ports block with:

```yaml
ports:
  - "${OPENCLAW_HOST_PORT:-19000}:19000"
  # Uncomment only when ACME_METHOD=http:
  # - "80:80"
```

Replace the volumes block with:

```yaml
volumes:
  - ./services/nginx/nginx.conf.template:/etc/nginx/nginx.conf.template:ro
  - nginx-certs:/etc/nginx/certs
```

And in the top-level `volumes:` section replace `nginx-acme-state:` with `nginx-certs:`.

### 5. Update `.env`

Add the following to your `.env` (on top of the base variables):

```bash
# Certificate validation method
ACME_METHOD=dns-route53

# AWS Route53 credentials (dns-route53 only)
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key

# Cloudflare API token (dns-cloudflare only)
# CLOUDFLARE_DNS_API_TOKEN=your-cloudflare-token

# GCP service account JSON (dns-google only)
# GOOGLE_APPLICATION_CREDENTIALS_JSON={"type":"service_account",...}
```

### 6. Rebuild

```bash
docker compose down
docker compose up -d --build
docker compose logs -f nginx
```

A successful DNS-01 issuance looks like:

```
nginx  | [nginx-acme] Using DNS-01 via AWS Route53
nginx  | [nginx-acme] Registering ACME account for admin@example.com...
nginx  | [nginx-acme] Issuing cert for example.com...
nginx  | [nginx-acme] Cert installed to /etc/nginx/certs.
nginx  | [nginx-acme] Starting nginx...
```

---

## Renewal behaviour

acme.sh runs a 12-hour loop inside the nginx container. When a certificate is within 30 days of expiry it renews automatically and signals `nginx -s reload` — no downtime for DNS-01 methods. The cert and acme.sh account data are persisted in the `nginx-certs` Docker volume, so container restarts do not re-issue from scratch.

> Let's Encrypt rate-limits to 5 duplicate certificates per week per domain. Avoid unnecessary `docker compose down -v` teardowns.
