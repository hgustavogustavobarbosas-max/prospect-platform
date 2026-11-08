"""Direitos do titular (LGPD art. 18): exportar e apagar dados vinculados a um telefone/e-mail."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.models import Consent, Contact, Interaction, Lead, SuppressionEntry
from app.services import audit
from app.services.normalize import normalize_identifier

ERASED = "[removido a pedido do titular]"


def _contacts_for(db: Session, ident: str) -> list[Contact]:
    if "@" in ident:  # e-mail e cifrado: varredura com decifragem (adequado ao porte do MVP)
        return [c for c in db.scalars(select(Contact).where(Contact.deleted_at.is_(None))).all()
                if (c.email or "").lower() == ident]
    return list(db.scalars(select(Contact).where(Contact.phone_e164 == ident, Contact.deleted_at.is_(None))).all())


def _lead_ids(db: Session, contacts: list[Contact]) -> list:
    biz = {c.business_id for c in contacts}
    if not biz:
        return []
    return list(db.scalars(select(Lead.id).where(Lead.business_id.in_(biz))).all())


def export_data(db: Session, identifier: str) -> dict:
    ident = normalize_identifier(identifier)
    if ident is None:
        raise ValueError("identificador invalido")
    contacts = _contacts_for(db, ident)
    leads = _lead_ids(db, contacts)
    inter = db.scalars(select(Interaction).where(Interaction.lead_id.in_(leads)).order_by(Interaction.created_at)).all() if leads else []
    consents = db.scalars(select(Consent).where(Consent.identifier == ident)).all()
    sup = db.scalar(select(SuppressionEntry).where(SuppressionEntry.identifier == ident))
    return {
        "identifier": ident,
        "contacts": [{"id": str(c.id), "name": c.name, "phone": c.phone, "email": c.email} for c in contacts],
        "interactions": [{"direction": i.direction, "content": i.content, "at": str(i.created_at)} for i in inter],
        "consents": [{"channel": c.channel, "status": c.status, "basis": c.basis, "at": str(c.occurred_at)} for c in consents],
        "suppressed": bool(sup),
    }


def erase_data(db: Session, identifier: str, who: Principal) -> dict:
    """Anonimiza contatos e mensagens. Mantem a entrada de supressao se houver (honrar opt-out e obrigacao
    legitima); apaga os registros de consentimento quando nao ha supressao."""
    ident = normalize_identifier(identifier)
    if ident is None:
        raise ValueError("identificador invalido")
    contacts = _contacts_for(db, ident)
    leads = _lead_ids(db, contacts)
    n_inter = 0
    for i in db.scalars(select(Interaction).where(Interaction.lead_id.in_(leads))).all() if leads else []:
        i.content, i.meta = ERASED, None
        n_inter += 1
    for c in contacts:
        c.name = c.phone = c.email = c.phone_e164 = None
        c.deleted_at = datetime.now(UTC)
    retained = []
    if db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.identifier == ident)):
        retained.append("suppression_list")
    else:
        for c in db.scalars(select(Consent).where(Consent.identifier == ident)).all():
            db.delete(c)
    audit.record(db, who, "erase", "privacy", "titular", {"contacts": len(contacts), "interactions": n_inter})
    return {"contacts_erased": len(contacts), "interactions_anonymized": n_inter, "retained": retained}
