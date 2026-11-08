import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.deps import Principal, reader, writer
from app.api.deps_clients import (
    get_app_settings,
    get_llm_client,
    get_optional_places_client,
    get_places_client,
)
from app.core.config import Settings
from app.db.session import get_db
from app.models import Business, Lead, ProspectingRun
from app.services import audit, prospecting
from app.services.prospecting import ProspectingError
from app.services.quota import usage_today

router = APIRouter(prefix="/prospecting", tags=["prospecting"])


def _run_or_404(db: Session, run_id: uuid.UUID) -> ProspectingRun:
    run = db.get(ProspectingRun, run_id)
    if run is None:
        raise HTTPException(404, "Nao encontrado")
    return run


@router.post("/runs", response_model=s.RunRead, status_code=201)
def start_run(
    body: s.RunCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    places=Depends(get_places_client),
    llm=Depends(get_llm_client),
    who: Principal = Depends(writer),
):
    """Cria uma busca e executa ate `max_pages` paginas. Se sobrar pagina, use /continue."""
    query = body.text_query or f"{body.segment} em {body.region}"
    run = ProspectingRun(
        segment=body.segment, region=body.region, text_query=query,
        page_size=body.page_size, status="partial",
    )
    db.add(run)
    db.flush()
    audit.record(db, who, "create", "prospecting_runs", run.id)
    db.commit()
    prospecting.run_pages(db, run, places, settings, llm, body.max_pages)
    db.refresh(run)
    return run


@router.post("/runs/{run_id}/continue", response_model=s.RunRead)
def continue_run(
    run_id: uuid.UUID,
    body: s.RunContinue | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    places=Depends(get_places_client),
    llm=Depends(get_llm_client),
    _: Principal = Depends(writer),
):
    run = _run_or_404(db, run_id)
    if run.status == "done":
        raise HTTPException(409, "Busca ja concluida")
    prospecting.run_pages(db, run, places, settings, llm, (body.max_pages if body else 1))
    db.refresh(run)
    return run


@router.get("/runs", response_model=list[s.RunRead])
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(reader),
):
    stmt = select(ProspectingRun).order_by(ProspectingRun.created_at.desc())
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.get("/runs/{run_id}", response_model=s.RunRead)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db), _: Principal = Depends(reader)):
    return _run_or_404(db, run_id)


@router.post("/leads/{lead_id}/score", response_model=s.LeadRead)
def rescore(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    places=Depends(get_optional_places_client),
    llm=Depends(get_llm_client),
    _: Principal = Depends(writer),
):
    """Recalcula o score. Para leads do Places (modo strict) busca os dados ao vivo, sem persisti-los."""
    lead = db.get(Lead, lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(404, "Nao encontrado")
    try:
        return prospecting.rescore_lead(db, lead, places, settings, llm)
    except ProspectingError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/businesses/{business_id}/live", response_model=s.LiveDetails)
def live_details(
    business_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    places=Depends(get_optional_places_client),
    _: Principal = Depends(writer),
):
    """Dados atuais do Places (nome, telefone, site) para uso imediato. Nao sao gravados."""
    biz = db.get(Business, business_id)
    if biz is None or biz.deleted_at is not None:
        raise HTTPException(404, "Nao encontrado")
    try:
        place = prospecting.fetch_live(db, biz, places, settings)
    except ProspectingError as exc:
        raise HTTPException(exc.status, exc.message) from None
    db.commit()  # contabiliza a chamada
    return place


@router.post("/purge-expired")
def purge_expired(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    who: Principal = Depends(writer),
):
    """Retencao: agende diariamente no n8n. So afeta o modo permissive."""
    n = prospecting.purge_expired(db, settings)
    audit.record(db, who, "purge", "businesses", "places-cache", {"count": n})
    db.commit()
    return {"purged": n}


@router.get("/usage", response_model=list[s.UsageRead])
def usage(db: Session = Depends(get_db), _: Principal = Depends(reader)):
    return usage_today(db)
