from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OutboxEvent


def enqueue(db: Session, topic: str, payload: dict, key: str) -> OutboxEvent:
    """Idempotente: a mesma chave devolve o evento existente."""
    stmt = select(OutboxEvent).where(OutboxEvent.idempotency_key == key)
    existing = db.scalar(stmt)
    if existing:
        return existing
    event = OutboxEvent(topic=topic, payload=payload, idempotency_key=key)
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        return db.scalar(stmt)
    return event


def notify_human(db: Session, key: str, text: str, **extra) -> OutboxEvent:
    return enqueue(db, "notify_human", {"text": text, **extra}, key)


MAX_ATTEMPTS = 5


def claim(db: Session, topics: list[str], limit: int = 20) -> list[OutboxEvent]:
    """Reserva eventos pendentes (SKIP LOCKED). Respeita o kill switch para topicos send_*."""
    from datetime import UTC, datetime

    from app.services.flags import get_flag

    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status == "pending", OutboxEvent.topic.in_(topics),
            OutboxEvent.available_at <= datetime.now(UTC),
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if not get_flag(db, "sending_enabled"):
        stmt = stmt.where(~OutboxEvent.topic.startswith("send_", autoescape=True))
    events = list(db.scalars(stmt).all())
    for e in events:
        e.status = "processing"
        e.attempts += 1
    db.flush()
    return events


def mark_done(event: OutboxEvent, note: str | None = None) -> None:
    event.status, event.last_error = "done", note


def mark_failed(event: OutboxEvent, error: str, *, permanent: bool = False, delay_minutes: int | None = None) -> None:
    from datetime import UTC, datetime, timedelta

    event.last_error = error[:1000]
    if permanent or event.attempts >= MAX_ATTEMPTS:
        event.status = "dead"  # dead-letter: exige intervencao humana
    else:
        event.status = "pending"
        minutes = delay_minutes if delay_minutes is not None else 2**event.attempts
        event.available_at = datetime.now(UTC) + timedelta(minutes=minutes)
