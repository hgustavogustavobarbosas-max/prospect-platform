"""Rotinas de manutencao do CRM e do outbox (agendadas pelo n8n, decididas aqui)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.models import Conversation, Interaction, Lead, Opportunity, OutboxEvent, Preview
from app.services import audit
from app.services.followups import aware
from app.services.lead_state import can_transition

SYSTEM = Principal("system:housekeeping", "service")
IDLE_CONVERSATION_DAYS = 7
STALE_LEAD_DAYS = 30
STUCK_OUTBOX_MINUTES = 30


def housekeeping(db: Session) -> dict:
    now = datetime.now(UTC)
    result = {"expired_opportunities": 0, "closed_conversations": 0, "lost_leads": 0, "requeued_outbox": 0, "expired_previews": 0}

    for opp in db.scalars(
        select(Opportunity).where(
            Opportunity.status.in_(["draft", "sent"]), Opportunity.valid_until.is_not(None),
            Opportunity.valid_until < now, Opportunity.deleted_at.is_(None),
        )
    ).all():
        opp.status = "expired"
        result["expired_opportunities"] += 1

    def last_activity(lead_id, fallback):
        last = db.scalar(select(func.max(Interaction.created_at)).where(Interaction.lead_id == lead_id))
        return aware(last) or aware(fallback)

    idle = now - timedelta(days=IDLE_CONVERSATION_DAYS)
    for conv in db.scalars(
        select(Conversation).where(Conversation.status == "open", Conversation.deleted_at.is_(None))
    ).all():
        if last_activity(conv.lead_id, conv.created_at) < idle:
            conv.status = "closed"
            result["closed_conversations"] += 1

    stale = now - timedelta(days=STALE_LEAD_DAYS)
    for lead in db.scalars(
        select(Lead).where(Lead.status.in_(["contacted", "replying"]), Lead.deleted_at.is_(None))
    ).all():
        if last_activity(lead.id, lead.updated_at) < stale and can_transition(lead.status, "lost"):
            previous, lead.status = lead.status, "lost"
            audit.record(db, SYSTEM, "transition", "leads", lead.id, {"from": previous, "to": "lost", "why": "inativo"})
            result["lost_leads"] += 1

    stuck = now - timedelta(minutes=STUCK_OUTBOX_MINUTES)
    for ev in db.scalars(
        select(OutboxEvent).where(OutboxEvent.status == "processing", OutboxEvent.updated_at < stuck)
    ).all():
        ev.status, ev.available_at = "pending", now  # worker caiu antes do ack: reenfileira
        result["requeued_outbox"] += 1

    for prev in db.scalars(select(Preview).where(Preview.status == "active", Preview.expires_at < now)).all():
        prev.status, prev.html = "expired", None  # previa temporaria: apaga o conteudo ao expirar
        result["expired_previews"] += 1

    db.commit()
    return result
