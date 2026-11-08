"""Webhook da Meta (publico, assinado) e drenagem das filas de entrada/saida."""

import json

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, reader, writer
from app.api.deps_clients import (
    build_agent_llm,
    build_whatsapp,
    get_agent_llm,
    get_app_settings,
    get_whatsapp_client,
)
from app.core.config import Settings
from app.core.ratelimit import rate_limit
from app.core.webhook_security import verify_signature
from app.db.session import SessionLocal, get_db
from app.models import OutboxEvent
from app.services import wa_inbound, wa_sender
from app.services.whatsapp import parse_webhook, tokens_match

log = structlog.get_logger()
MAX_BODY = 1_048_576  # 1 MiB

public = APIRouter(tags=["whatsapp-webhook"])
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def drain_all(db: Session, settings: Settings, llm, client) -> dict:
    return {
        "inbound": wa_inbound.drain_inbound(db, settings, llm),
        "outbound": wa_sender.drain_sends(db, settings, client),
    }


def _drain_background(settings: Settings) -> None:
    try:
        with SessionLocal() as db:
            drain_all(db, settings, build_agent_llm(settings), build_whatsapp(settings))
    except Exception as exc:  # noqa: BLE001 - o sweeper do n8n (WF09) cobre qualquer falha aqui
        log.error("drain_background_falhou", error=type(exc).__name__)


@public.get("/webhooks/whatsapp", dependencies=[Depends(rate_limit("wa-verify", 30, 60))])
def verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_app_settings),
):
    """Handshake da Meta: devolve hub.challenge se o token confere (comparacao em tempo constante)."""
    if hub_mode == "subscribe" and tokens_match(hub_verify_token, settings.whatsapp_verify_token):
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(403, "Token de verificacao invalido")


@public.post("/webhooks/whatsapp", dependencies=[Depends(rate_limit("wa-hook", 600, 60))])
async def receive(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
):
    raw = await request.body()  # a assinatura vale para o corpo BRUTO: valide antes de interpretar
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Corpo grande demais")
    if not settings.whatsapp_app_secret:
        raise HTTPException(503, "WHATSAPP_APP_SECRET nao configurado")
    if not verify_signature(raw, request.headers.get("x-hub-signature-256"), settings.whatsapp_app_secret):
        raise HTTPException(401, "Assinatura invalida")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "JSON invalido") from None
    msgs, statuses = parse_webhook(payload)
    wa_inbound.store_inbound(db, msgs)  # duravel e idempotente por wamid
    wa_inbound.apply_statuses(db, statuses)
    db.commit()
    if msgs:
        background.add_task(_drain_background, settings)  # resposta rapida a Meta; processa em seguida
    return {"ok": True}


@router.post("/drain")
def drain(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    llm=Depends(get_agent_llm),
    client=Depends(get_whatsapp_client),
    _: Principal = Depends(writer),
):
    """Processa entrada e saida pendentes. O WF09 chama a cada minuto (rede de seguranca)."""
    return drain_all(db, settings, llm, client)


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: Principal = Depends(reader),
):
    counts = dict(
        db.execute(
            select(OutboxEvent.topic, func.count(OutboxEvent.id))
            .where(OutboxEvent.status == "pending", OutboxEvent.topic.in_(["wa_inbound", "send_whatsapp", "send_whatsapp_template"]))
            .group_by(OutboxEvent.topic)
        ).all()
    )
    return {
        "enabled": settings.whatsapp_enabled,
        "configured": {
            "access_token": bool(settings.whatsapp_access_token),
            "phone_number_id": bool(settings.whatsapp_phone_number_id),
            "app_secret": bool(settings.whatsapp_app_secret),
            "verify_token": bool(settings.whatsapp_verify_token),
        },
        "pending": counts,
    }
