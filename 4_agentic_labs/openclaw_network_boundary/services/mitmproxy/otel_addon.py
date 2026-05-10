# Copyright (c) 2026 markosluga
# SPDX-License-Identifier: Apache-2.0
#
# mitmproxy OTel addon — emits an OTLP span for every intercepted request/
# response pair and for TLS handshake errors (certificate pinning).

import time
import logging

from mitmproxy import http, tls as mitm_tls

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger("otel_addon")

_OTEL_ENDPOINT = "http://otel-collector:4317"
_SERVICE_NAME  = "mitmproxy.network-boundary"

# Maximum in-flight spans buffered when the collector is unreachable.
_MAX_QUEUE_SIZE    = 2048
_EXPORT_TIMEOUT_MS = 10_000
_SCHEDULE_DELAY_MS = 5_000


def _build_provider() -> TracerProvider:
    resource  = Resource.create({"service.name": _SERVICE_NAME})
    exporter  = OTLPSpanExporter(
        endpoint=_OTEL_ENDPOINT,
        insecure=True,
    )
    processor = BatchSpanProcessor(
        exporter,
        max_queue_size=_MAX_QUEUE_SIZE,
        export_timeout_millis=_EXPORT_TIMEOUT_MS,
        schedule_delay_millis=_SCHEDULE_DELAY_MS,
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    return provider


class OtelAddon:
    """
    Hooks into mitmproxy events and emits OpenTelemetry spans.

    Spans are buffered in-process and flushed over gRPC to otel-collector.
    If the collector is unreachable, BatchSpanProcessor retries and queues
    up to _MAX_QUEUE_SIZE spans before dropping; the addon itself never crashes.
    """

    def __init__(self) -> None:
        try:
            provider = _build_provider()
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer(_SERVICE_NAME)
            logger.info("OTel addon initialised — exporting to %s", _OTEL_ENDPOINT)
        except Exception:
            logger.exception("OTel addon failed to initialise; spans will be dropped.")
            self._tracer = None

    # ── Normal request/response ────────────────────────────────────────────────

    def response(self, flow: http.HTTPFlow) -> None:
        if self._tracer is None:
            return
        try:
            elapsed_ms = round(
                (flow.response.timestamp_end - flow.request.timestamp_start) * 1000
            )
            with self._tracer.start_as_current_span("outbound.request") as span:
                span.set_attribute("http.method",          flow.request.method)
                span.set_attribute("http.url",             flow.request.pretty_url)
                span.set_attribute("http.status_code",     flow.response.status_code)
                span.set_attribute("net.peer.name",        flow.request.host)
                span.set_attribute("net.peer.port",        flow.request.port)
                span.set_attribute("tls.version",
                    flow.server_conn.tls_version if flow.server_conn.tls_version else "none")
                span.set_attribute("http.response_time_ms", elapsed_ms)
        except Exception:
            logger.exception("Error emitting span for %s", flow.request.pretty_url)

    # ── TLS handshake errors (certificate pinning) ─────────────────────────────

    def tls_handshake_error(self, tls_client_hello: mitm_tls.ClientHelloData) -> None:
        if self._tracer is None:
            return
        try:
            with self._tracer.start_as_current_span("outbound.tls_error") as span:
                span.set_attribute("tls.pinning_detected", True)
                span.set_attribute("net.peer.name",
                    tls_client_hello.context.server.address.host
                    if tls_client_hello.context.server
                    else "unknown")
        except Exception:
            logger.exception("Error emitting TLS error span")


addons = [OtelAddon()]
