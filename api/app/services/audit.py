import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session, who, action: str, entity: str, entity_id: uuid.UUID | str, data: dict | None = None
) -> None:
    """Registra trilha de auditoria. `data` deve conter so nomes de campos, nunca PII."""
    db.add(
        AuditLog(
            actor=who.subject, role=who.role, action=action,
            entity=entity, entity_id=str(entity_id), data=data,
        )
    )
