"""Mensagens recebidas: fila duravel (idempotente por wamid) -> resolve o lead -> agente."""


import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Business, Contact, Interaction, Lead, OutboxEvent
from app.services import agent as agent_svc
from app.services import outbox_svc
from app.services.normalize import dedupe_key, normalize_phone_br
from app.services.outbox_svc import enqueue
from app.services.whatsapp import InboundMessage, StatusUpdate

log = structlog.get_logger()
TERMINAL = {"won", "lost", "suppressed"}


def store_inbound(db: Session, msgs: list[InboundMessage]) -> int:
    for m in msgs:
        enqueue(
            db, "wa_inbound",
            {
                "wamid": m.wamid, "from_phone": m.from_phone, "text": m.text,
                "message_type": m.message_type, "profile_name": m.profile_name,
            },
            f"wa-in-{m.wamid}",
        )
    return len(msgs)


def apply_statuses(db: Session, statuses: list[StatusUpdate]) -> None:
    """Recibos de entrega: atualizam a interacao e alertam em falhas."""
    for st in statuses:
        it = db.scalar(select(Interaction).where(Interaction.external_id == st.wamid))
        if it is None:
            continue
        meta = dict(it.meta or {})
        order = {"sent": 1, "delivered": 2, "read": 3, "failed": 9}
        if order.get(st.status, 0) >= order.get(meta.get("delivery", ""), 0):
            meta["delivery"] = st.status
        if st.status == "failed":
            meta["error_code"], meta["error_title"] = st.error_code, st.error_title
            outbox_svc.notify_human(
                db, f"wa-status-fail-{st.wamid}",
                f"Mensagem nao entregue (codigo {st.error_code}).", lead_id=str(it.lead_id),
                kind="delivery_failed",
            )
        it.meta = meta


def resolve_lead(db: Session, phone: str, profile_name: str | None) -> Lead:
    contacts = db.scalars(
        select(Contact).where(Contact.phone_e164 == phone, Contact.deleted_at.is_(None))
        .order_by(Contact.created_at.desc())
    ).all()
    fallback = None
    for c in contacts:
        leads = db.scalars(
            select(Lead).where(Lead.business_id == c.business_id, Lead.deleted_at.is_(None))
            .order_by(Lead.created_at.desc())
        ).all()
        for lead in leads:
            if lead.status not in TERMINAL:
                return lead
            fallback = fallback or lead
    if fallback is not None:
        return fallback
    # contato desconhecido (cliente chegou por conta propria): cria negocio/contato/lead
    h = dedupe_key(None, None, phone, None)
    biz = db.scalar(select(Business).where(Business.dedupe_hash == h))
    if biz is None:
        biz = Business(
            name=f"[WhatsApp] ***{phone[-4:]}", source="whatsapp_inbound", dedupe_hash=h,
            has_website=False,
        )
        db.add(biz)
        db.flush()
    db.add(Contact(business_id=biz.id, name=profile_name, phone=phone, phone_e164=phone))
    lead = Lead(business_id=biz.id)
    db.add(lead)
    db.flush()
    return lead


def drain_inbound(db: Session, settings: Settings, llm, limit: int = 20) -> dict:
    stats = {"processed": 0, "failed": 0}
    events = outbox_svc.claim(db, ["wa_inbound"], limit)
    db.commit()
    for ev in events:
        ev_id, p = ev.id, dict(ev.payload)
        try:
            phone = normalize_phone_br(p["from_phone"]) or p["from_phone"]
            lead = resolve_lead(db, phone, p.get("profile_name"))
            agent_svc.handle_inbound(
                db, settings, llm, lead=lead, text=p.get("text", ""), external_id=p["wamid"],
                message_type=p.get("message_type", "text"), from_phone=phone,
            )
            row = db.get(OutboxEvent, ev_id)
            outbox_svc.mark_done(row)
            db.commit()
            stats["processed"] += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.error("wa_inbound_erro", error=type(exc).__name__)
            row = db.get(OutboxEvent, ev_id)
            outbox_svc.mark_failed(row, f"erro_interno: {type(exc).__name__}")
            db.commit()
            stats["failed"] += 1
    return stats


