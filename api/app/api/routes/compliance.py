from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.deps import Principal, admin_only, reader, writer
from app.db.session import get_db
from app.models import Consent, SuppressionEntry
from app.services import audit
from app.services.compliance import can_contact
from app.services.normalize import normalize_identifier

router = APIRouter(tags=["compliance"])


def _ident_or_422(raw: str) -> str:
    ident = normalize_identifier(raw)
    if ident is None:
        raise HTTPException(422, "Identificador invalido (use e-mail ou telefone brasileiro)")
    return ident


def _suppress(db: Session, ident: str, reason: str, source: str | None) -> None:
    if not db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.identifier == ident)):
        db.add(SuppressionEntry(identifier=ident, reason=reason, source=source))


@router.post("/consents", response_model=s.ConsentRead, status_code=201)
def register_consent(
    body: s.ConsentCreate, db: Session = Depends(get_db), who: Principal = Depends(writer)
):
    """Registro append-only. Revogar consentimento suprime o identificador em todos os canais."""
    ident = _ident_or_422(body.identifier)
    consent = Consent(**{**body.model_dump(), "identifier": ident})
    db.add(consent)
    if body.status == "revoked":
        _suppress(db, ident, "opt_out", body.source)
    db.flush()
    audit.record(db, who, "create", "consents", consent.id, {"status": body.status})
    db.commit()
    db.refresh(consent)
    return consent


@router.get("/consents", response_model=list[s.ConsentRead])
def list_consents(
    identifier: str = Query(...),
    db: Session = Depends(get_db),
    _: Principal = Depends(reader),
):
    ident = _ident_or_422(identifier)
    stmt = select(Consent).where(Consent.identifier == ident).order_by(Consent.occurred_at.desc())
    return db.scalars(stmt).all()


@router.get("/compliance/can-contact", response_model=s.CanContactOut)
def check_can_contact(
    identifier: str = Query(...),
    channel: s.Channel = Query(...),
    db: Session = Depends(get_db),
    _: Principal = Depends(reader),
):
    """O n8n DEVE chamar isto antes de qualquer envio."""
    allowed, reason = can_contact(db, identifier, channel)
    return s.CanContactOut(identifier=identifier, channel=channel, allowed=allowed, reason=reason)


@router.post("/suppression", response_model=s.SuppressionRead, status_code=201)
def add_suppression(
    body: s.SuppressionCreate, db: Session = Depends(get_db), who: Principal = Depends(writer)
):
    ident = _ident_or_422(body.identifier)
    existing = db.scalar(select(SuppressionEntry).where(SuppressionEntry.identifier == ident))
    if existing:
        return existing  # idempotente
    entry = SuppressionEntry(identifier=ident, reason=body.reason, source=body.source)
    db.add(entry)
    db.flush()
    audit.record(db, who, "create", "suppression_list", entry.id, {"reason": body.reason})
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/suppression", response_model=list[s.SuppressionRead])
def list_suppression(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(reader),
):
    stmt = select(SuppressionEntry).order_by(SuppressionEntry.created_at.desc())
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.delete("/suppression", status_code=204)
def remove_suppression(
    identifier: str = Query(...),
    db: Session = Depends(get_db),
    who: Principal = Depends(admin_only),
):
    """Somente admin: reverter uma supressao exige decisao humana e fica auditado."""
    ident = _ident_or_422(identifier)
    entry = db.scalar(select(SuppressionEntry).where(SuppressionEntry.identifier == ident))
    if entry is None:
        raise HTTPException(404, "Nao encontrado")
    audit.record(db, who, "delete", "suppression_list", entry.id)
    db.delete(entry)
    db.commit()
    return Response(status_code=204)
