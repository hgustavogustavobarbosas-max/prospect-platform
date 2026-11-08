from sqlalchemy.orm import Session

from app.models import SystemFlag

ALLOWED_FLAGS = {"sending_enabled"}


def get_flag(db: Session, key: str, default: bool = True) -> bool:
    row = db.get(SystemFlag, key)
    return default if row is None else row.value


def set_flag(db: Session, key: str, value: bool, by: str) -> SystemFlag:
    row = db.get(SystemFlag, key)
    if row is None:
        row = SystemFlag(key=key, value=value, updated_by=by)
        db.add(row)
    else:
        row.value, row.updated_by = value, by
    db.flush()
    return row
