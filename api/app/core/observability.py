"""Sentry (opcional), metricas Prometheus e cabecalhos de seguranca."""

import hmac
import time

import structlog
from fastapi import FastAPI, HTTPException, Request, Response

from app.core.config import Settings

log = structlog.get_logger()


def init_sentry(dsn: str | None, env: str) -> None:
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, environment=env, send_default_pii=False, traces_sample_rate=0.0)


def add_security_headers(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.is_production:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


def add_metrics(app: FastAPI, settings: Settings, session_factory) -> None:
    if not settings.metrics_enabled:
        return
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    reg = CollectorRegistry()
    requests = Counter("http_requests_total", "Requisicoes HTTP", ["method", "route", "status"], registry=reg)
    latency = Histogram("http_request_seconds", "Latencia", ["route"], registry=reg,
                        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
    outbox = Gauge("outbox_events", "Eventos do outbox por status", ["status"], registry=reg)
    handoffs = Gauge("open_handoffs", "Conversas aguardando humano", registry=reg)

    @app.middleware("http")
    async def measure(request: Request, call_next):
        start = time.perf_counter()
        resp = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "nao_roteado")  # template, nunca o path real (sem IDs/tokens)
        requests.labels(request.method, route, str(resp.status_code)).inc()
        latency.labels(route).observe(time.perf_counter() - start)
        return resp

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        auth = request.headers.get("authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {settings.service_api_key}"):
            raise HTTPException(401, "nao autorizado")
        from sqlalchemy import func, select

        from app.models import Conversation, OutboxEvent

        with session_factory() as db:
            for st, n in db.execute(select(OutboxEvent.status, func.count(OutboxEvent.id)).group_by(OutboxEvent.status)).all():
                outbox.labels(st).set(n)
            handoffs.set(db.scalar(select(func.count(Conversation.id)).where(Conversation.status == "handoff")) or 0)
        return Response(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
