import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.deps import Principal, writer
from app.db.session import get_db
from app.models import OutboxEvent
from app.services import outbox_svc
from app.services.flags import get_flag

router = APIRouter(prefix="/outbox", tags=["outbox"])


@router.post("", response_model=s.OutboxRead)
def enqueue(
    body: s.OutboxCreate,
    response: Response,
    db: Session = Depends(get_db),
    _: Principal = Depends(writer),
):
    """Idempotente: a mesma `idempotency_key` devolve o evento existente (200) em vez de duplicar."""
    existing = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == body.idempotency_key))
    if existing:
        return existing
    event = OutboxEvent(**body.model_dump())
    db.add(event)
    try:
        db.commit()
    except IntegrityError:  # corrida entre duas requisicoes com a mesma chave
        db.rollback()
        return db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == body.idempotency_key))
    db.refresh(event)
    response.status_code = 201
    return event


@router.post("/claim", response_model=list[s.OutboxRead])
def claim(
    topic: str | None = Query(default=None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Principal = Depends(writer),
):
    """Reserva eventos pendentes (FOR UPDATE SKIP LOCKED): dois workers nunca pegam o mesmo."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == "pending", OutboxEvent.available_at <= datetime.now(UTC))
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if topic:
        stmt = stmt.where(OutboxEvent.topic == topic)
    if not get_flag(db, "sending_enabled"):  # kill switch: so topicos send_* ficam retidos
        stmt = stmt.where(~OutboxEvent.topic.startswith("send_", autoescape=True))
    events = db.scalars(stmt).all()
    for e in events:
        e.status = "processing"
        e.attempts += 1
    db.commit()
    return events


@router.post("/{event_id}/ack", response_model=s.OutboxRead)
def ack(
    event_id: uuid.UUID,
    body: s.OutboxAck,
    db: Session = Depends(get_db),
    _: Principal = Depends(writer),
):
    event = db.get(OutboxEvent, event_id)
    if event is None:
        raise HTTPException(404, "Nao encontrado")
    if body.success:
        outbox_svc.mark_done(event)
    else:
        outbox_svc.mark_failed(event, body.error or "erro")
    db.commit()
    db.refresh(event)
    return event
