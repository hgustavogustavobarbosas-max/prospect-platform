"""Rotacao de chaves: reescreve todos os campos cifrados com a PRIMEIRA chave de DATA_ENCRYPTION_KEYS.

Passos: 1) coloque a chave nova NA FRENTE da lista (a antiga continua para ler);
2) docker compose exec api python scripts/reencrypt.py; 3) depois remova a chave antiga.
"""
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.models import Briefing, Contact, Interaction, Opportunity, Ticket

TARGETS = [
    (Contact, ["name", "phone", "email"]), (Interaction, ["content"]), (Briefing, ["data"]),
    (Ticket, ["body"]), (Opportunity, ["client_name", "proposal_notes", "nps_comment"]),
]


def main() -> None:
    total = 0
    with SessionLocal() as db:
        for model, cols in TARGETS:
            for obj in db.scalars(select(model)).yield_per(500):
                for c in cols:
                    if getattr(obj, c) is not None:
                        flag_modified(obj, c)
                total += 1
            db.commit()
    print(f"{total} registros reescritos com a chave atual")


if __name__ == "__main__":
    main()
