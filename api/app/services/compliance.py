"""Politica de contato (LGPD). Regras documentadas em docs/adr/0002-politica-de-contato.md."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent, SuppressionEntry
from app.services.normalize import normalize_identifier
from app.services.optout import OPTOUT_WORDS, is_optout_message  # noqa: F401  (reexport)

def can_contact(db: Session, identifier: str, channel: str) -> tuple[bool, str]:
    ident = normalize_identifier(identifier)
    if ident is None:
        return False, "identificador_invalido"
    if db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.identifier == ident)):
        return False, "suprimido"
    latest = db.scalar(
        select(Consent)
        .where(Consent.identifier == ident, Consent.channel == channel)
        .order_by(Consent.occurred_at.desc())
        .limit(1)
    )
    if latest is not None and latest.status == "revoked":
        return False, "consentimento_revogado"
    if latest is not None and latest.status == "granted":
        return True, "opt_in"
    if channel == "whatsapp":
        return False, "sem_opt_in_whatsapp"  # WhatsApp exige opt-in previo
    return True, "legitimo_interesse"
