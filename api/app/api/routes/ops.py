"""Catalogo, kill switch, agente, follow-ups, manutencao e monitoramento (Parte 3)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.crud import build_crud_router
from app.api.deps import Principal, admin_only, reader, writer
from app.api.deps_clients import get_agent_llm, get_app_settings
from app.core.config import Settings
from app.db.session import get_db
from app.models import Lead, Plan, SystemFlag
from app.services import agent as agent_svc
from app.services import crm_sync, flags, followups, monitoring

plans_router = build_crud_router(
    model=Plan, prefix="/plans", tag="plans",
    create_schema=s.PlanCreate, update_schema=s.PlanUpdate, read_schema=s.PlanRead,
    filters=("code",),
)

router = APIRouter(tags=["operations"])


@router.get("/system/flags", response_model=list[s.FlagRead])
def list_flags(db: Session = Depends(get_db), _: Principal = Depends(reader)):
    rows = {r.key: r for r in db.scalars(select(SystemFlag)).all()}
    return [
        rows.get(k) or s.FlagRead(key=k, value=True, updated_by=None) for k in sorted(flags.ALLOWED_FLAGS)
    ]


@router.put("/system/flags/{key}", response_model=s.FlagRead)
def put_flag(
    key: str, body: s.FlagSet, db: Session = Depends(get_db), who: Principal = Depends(admin_only)
):
    """Kill switch: `sending_enabled=false` pausa a entrega de TODOS os eventos send_* no outbox."""
    if key not in flags.ALLOWED_FLAGS:
        raise HTTPException(404, "Flag desconhecida")
    row = flags.set_flag(db, key, body.value, who.subject)
    db.commit()
    return row


@router.post("/agent/respond", response_model=s.AgentOut)
def agent_respond(
    body: s.AgentIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    llm=Depends(get_agent_llm),
    _: Principal = Depends(writer),
):
    """Processa UMA mensagem recebida. Idempotente por `external_id` (ex.: wamid)."""
    lead = db.get(Lead, body.lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(404, "Lead nao encontrado")
    result = agent_svc.handle_inbound(
        db, settings, llm, lead=lead, text=body.text, external_id=body.external_id,
        message_type=body.message_type, from_phone=body.from_phone,
    )
    return s.AgentOut(
        action=result.action, reply=result.reply, conversation_id=result.conversation_id,
        outbox_id=result.outbox_id, flags=result.flags,
    )


@router.get("/followups/due", response_model=list[s.FollowupDue])
def followups_due(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: Principal = Depends(reader),
):
    return followups.due_followups(db, settings, limit)


@router.post("/crm/housekeeping")
def housekeeping(db: Session = Depends(get_db), _: Principal = Depends(writer)):
    return crm_sync.housekeeping(db)


@router.get("/monitoring/summary")
def monitoring_summary(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: Principal = Depends(reader),
):
    return monitoring.summary(db, settings)
