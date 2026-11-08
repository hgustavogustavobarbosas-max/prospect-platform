"""Entrega do outbox no WhatsApp: janela de 24h, opt-in, limites e tratamento de erro da Meta."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Contact, Interaction, Lead, OutboxEvent
from app.services import outbox_svc
from app.services.compliance import can_contact
from app.services.followups import aware
from app.services.outbox_svc import notify_human
from app.services.quota import QuotaExceeded, reserve_call
from app.services.whatsapp import WhatsAppError, template_payload, text_payload, within_window

log = structlog.get_logger()
TOPICS = ["send_whatsapp", "send_whatsapp_template"]


def _defer(ev: OutboxEvent, minutes: int, note: str) -> None:
    from datetime import timedelta

    ev.status, ev.last_error = "pending", note
    ev.attempts = max(0, ev.attempts - 1)  # problema nosso (config/limite): nao gasta tentativa
    ev.available_at = datetime.now(UTC) + timedelta(minutes=minutes)


def _phone_for(db: Session, lead: Lead) -> str | None:
    return db.scalar(
        select(Contact.phone_e164)
        .where(
            Contact.business_id == lead.business_id, Contact.phone_e164.is_not(None),
            Contact.deleted_at.is_(None),
        )
        .order_by(Contact.created_at.desc()).limit(1)
    )


def _send_one(db: Session, settings: Settings, client, ev: OutboxEvent, stats: dict) -> None:
    p = ev.payload
    lead = db.get(Lead, uuid.UUID(p["lead_id"])) if p.get("lead_id") else None
    if lead is None:
        outbox_svc.mark_failed(ev, "lead_inexistente", permanent=True)
        stats["failed"] += 1
        return
    interaction = db.get(Interaction, uuid.UUID(p["interaction_id"])) if p.get("interaction_id") else None
    if interaction is not None and interaction.external_id:
        outbox_svc.mark_done(ev, "ja_enviado")  # retry apos queda entre o envio e o ack
        return
    phone = _phone_for(db, lead)
    if phone is None:
        outbox_svc.mark_failed(ev, "sem_telefone", permanent=True)
        notify_human(db, f"nophone-{lead.id}", "Mensagem sem telefone de destino.", lead_id=str(lead.id))
        stats["failed"] += 1
        return

    is_template = ev.topic == "send_whatsapp_template"
    allowed, reason = can_contact(db, phone, "whatsapp")
    # a confirmacao do proprio opt-out e a unica mensagem permitida a quem acabou de ser suprimido
    suppressed = reason in ("suprimido", "consentimento_revogado") and p.get("kind") != "optout"
    if suppressed or (is_template and not allowed):
        outbox_svc.mark_done(ev, f"cancelado: {reason}")  # checagem de conformidade NO MOMENTO do envio
        stats["cancelled"] += 1
        return
    if client is None:
        _defer(ev, 5, "whatsapp_nao_configurado")
        stats["deferred"] += 1
        return

    if is_template:
        try:
            reserve_call(db, "wa_template", settings.whatsapp_max_templates_per_day)
        except QuotaExceeded:
            _defer(ev, 60, "limite_diario_de_templates")
            stats["deferred"] += 1
            return
        wa_payload = template_payload(phone, p["template"], settings.whatsapp_template_language)
    else:
        last_in = aware(
            db.scalar(
                select(func.max(Interaction.created_at)).where(
                    Interaction.lead_id == lead.id, Interaction.direction == "in"
                )
            )
        )
        if not within_window(last_in, datetime.now(UTC)):
            outbox_svc.mark_failed(ev, "fora_da_janela_24h: use um template aprovado", permanent=True)
            notify_human(
                db, f"window-{ev.id}", "Mensagem nao enviada: janela de 24h fechada (use template).",
                lead_id=str(lead.id),
            )
            stats["failed"] += 1
            return
        wa_payload = text_payload(phone, p["text"])

    try:
        wamid = client.send(wa_payload)
    except WhatsAppError as exc:
        log.warning("whatsapp_envio_falhou", kind=exc.kind, code=exc.code, status=exc.http_status)
        if exc.kind == "auth":
            _defer(ev, 15, str(exc))
            notify_human(
                db, f"wa-auth-{datetime.now(UTC).date()}",
                "WhatsApp: token invalido ou expirado. Envios parados ate corrigir WHATSAPP_ACCESS_TOKEN.",
                kind="whatsapp_auth",
            )
        elif exc.kind == "retry":
            outbox_svc.mark_failed(ev, str(exc))
        else:  # window | permanent
            outbox_svc.mark_failed(ev, str(exc), permanent=True)
            notify_human(db, f"wa-fail-{ev.id}", f"Mensagem nao entregue ({exc.kind}).", lead_id=str(lead.id))
        stats["failed"] += 1
        return

    if interaction is not None:
        interaction.external_id = wamid
        interaction.meta = {**(interaction.meta or {}), "delivery": "sent"}
    else:
        db.add(
            Interaction(
                lead_id=lead.id, channel="whatsapp", direction="out", external_id=wamid,
                content=f"[template:{p.get('template')}]",
                meta={"kind": "followup", "delivery": "sent", "attempt": p.get("attempt")},
                created_at=datetime.now(UTC),
            )
        )
    outbox_svc.mark_done(ev)
    stats["sent"] += 1


def drain_sends(db: Session, settings: Settings, client, limit: int = 20) -> dict:
    stats = {"sent": 0, "cancelled": 0, "failed": 0, "deferred": 0}
    events = outbox_svc.claim(db, TOPICS, limit)
    db.commit()
    for ev in events:
        ev_id = ev.id
        try:
            _send_one(db, settings, client, ev, stats)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - uma mensagem ruim nao pode parar a fila
            db.rollback()
            log.error("whatsapp_drain_erro", error=type(exc).__name__)
            row = db.get(OutboxEvent, ev_id)
            outbox_svc.mark_failed(row, f"erro_interno: {type(exc).__name__}")
            db.commit()
            stats["failed"] += 1
    return stats
