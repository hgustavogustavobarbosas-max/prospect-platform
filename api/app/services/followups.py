"""Quem deve receber follow-up agora. O servidor decide; o n8n so agenda e enfileira."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Contact, Conversation, Interaction, Lead, OutboxEvent
from app.services.compliance import can_contact


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def due_followups(db: Session, settings: Settings, limit: int = 50) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(hours=settings.followup_after_hours)
    leads = db.scalars(
        select(Lead)
        .where(Lead.status.in_(["contacted", "replying"]), Lead.deleted_at.is_(None))
        .order_by(Lead.updated_at)
    ).all()
    out: list[dict] = []
    for lead in leads:
        if len(out) >= limit:
            break
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.lead_id == lead.id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        if conv is not None and conv.status in ("handoff", "closed"):
            continue
        last = db.scalar(
            select(Interaction).where(Interaction.lead_id == lead.id)
            .order_by(Interaction.created_at.desc()).limit(1)
        )
        if last is not None and last.direction == "in":
            continue  # o cliente falou por ultimo: quem responde e o agente
        events = db.execute(
            select(func.count(OutboxEvent.id), func.max(OutboxEvent.created_at)).where(
                OutboxEvent.idempotency_key.like(f"followup-{lead.id}-%")
            )
        ).one()
        attempts = events[0] or 0
        if attempts >= settings.max_followups:
            continue
        ref = max(
            d for d in (aware(last.created_at) if last else None, aware(events[1]), aware(lead.updated_at))
            if d is not None
        )
        if ref > cutoff:
            continue
        phones = db.scalars(
            select(Contact.phone_e164).where(
                Contact.business_id == lead.business_id, Contact.phone_e164.is_not(None),
                Contact.deleted_at.is_(None),
            )
        ).all()
        # follow-up so para quem tem opt-in de WhatsApp registrado (e nao esta suprimido)
        if not any(can_contact(db, ph, "whatsapp")[0] for ph in phones):
            continue
        attempt = attempts + 1
        out.append(
            {
                "lead_id": lead.id, "attempt": attempt, "template": f"followup_{attempt}",
                "idempotency_key": f"followup-{lead.id}-{attempt}",
            }
        )
    return out
