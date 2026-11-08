import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from sqlalchemy import func, select

from app.api.router import api_router
from app.api.routes import health, public, whatsapp
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import add_metrics, add_security_headers, init_sentry
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Plan, User

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
init_sentry(settings.sentry_dsn, settings.app_env)
log = structlog.get_logger()


def seed_admin() -> None:
    if not (settings.admin_email and settings.admin_password):
        return
    email = settings.admin_email.lower()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(func.lower(User.email) == email)) is None:
            db.add(User(email=email, hashed_password=hash_password(settings.admin_password), role="admin"))
            db.commit()
            log.info("admin_criado", email=email)


DEFAULT_PLANS = [
    ("basic", "Basico", "Site simples de apresentacao. [Defina descricao e preco em PATCH /v1/plans/{id}]"),
    ("professional", "Profissional", "Site completo. [Defina descricao e preco em PATCH /v1/plans/{id}]"),
    ("custom", "Personalizado", "Projeto sob medida, orcado caso a caso."),
]


def seed_plans() -> None:
    """Cria os 3 planos SEM preco: o agente responde 'sob consulta' ate voce definir os valores."""
    with SessionLocal() as db:
        if db.scalar(select(func.count(Plan.id))) == 0:
            for code, name, desc in DEFAULT_PLANS:
                db.add(Plan(code=code, name=name, description=desc, active=True))
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_admin()
    seed_plans()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Prospect Platform API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info(
            "request", method=request.method, path=request.url.path,
            status=response.status_code, ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return response

    add_security_headers(app, settings)
    add_metrics(app, settings, SessionLocal)
    app.include_router(health.router)
    app.include_router(whatsapp.public)  # webhook da Meta (publico, assinado)
    app.include_router(public.router)  # links do cliente (token)
    app.include_router(api_router)
    return app


app = create_app()
