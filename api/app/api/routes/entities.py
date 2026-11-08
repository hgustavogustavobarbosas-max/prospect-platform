"""CRUD das entidades principais + regras de dominio (derivacoes e maquina de estados)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas as s
from app.api.crud import build_crud_router
from app.api.deps import Principal, writer
from app.db.session import get_db
from app.models import (
    Business,
    Contact,
    Conversation,
    Interaction,
    Lead,
    Opportunity,
    Payment,
)
from app.services import audit
from app.services.lead_state import TRANSITIONS, can_transition
from app.services.normalize import dedupe_key, normalize_cnpj, normalize_phone_br


# ---------- derivacoes ----------
def _derive_business(data: dict, current=None) -> dict:
    def pick(key):
        return data[key] if key in data else (getattr(current, key, None) if current else None)

    if "phone" in data:
        data["phone_e164"] = normalize_phone_br(data["phone"])
    if "cnpj" in data and data["cnpj"]:
        cnpj = normalize_cnpj(data["cnpj"])
        if cnpj is None:
            raise HTTPException(422, "CNPJ invalido")
        data["cnpj"] = cnpj
    if "website_url" in data:
        data["has_website"] = bool(data["website_url"])
    phone_e164 = data.get("phone_e164", getattr(current, "phone_e164", None))
    data["dedupe_hash"] = dedupe_key(pick("name"), pick("address"), phone_e164, pick("cnpj"))
    return data


def _derive_contact(data: dict, current=None) -> dict:
    if "phone" in data:
        data["phone_e164"] = normalize_phone_br(data["phone"])
    if data.get("email"):
        data["email"] = data["email"].lower()
    return data


business_router = build_crud_router(
    model=Business, prefix="/businesses", tag="businesses",
    create_schema=s.BusinessCreate, update_schema=s.BusinessUpdate, read_schema=s.BusinessRead,
    filters=("segment", "region", "place_id"),
    before_create=_derive_business, before_update=_derive_business,
)

contact_router = build_crud_router(
    model=Contact, prefix="/contacts", tag="contacts",
    create_schema=s.ContactCreate, update_schema=s.ContactUpdate, read_schema=s.ContactRead,
    filters=("business_id",),
    before_create=_derive_contact, before_update=_derive_contact,
)

lead_router = build_crud_router(
    model=Lead, prefix="/leads", tag="leads",
    create_schema=s.LeadCreate, update_schema=s.LeadUpdate, read_schema=s.LeadRead,
    filters=("business_id", "status", "tier"),
)


@lead_router.post("/{lead_id}/status", response_model=s.LeadRead)
def change_lead_status(
    lead_id: uuid.UUID,
    body: s.LeadStatusChange,
    db: Session = Depends(get_db),
    who: Principal = Depends(writer),
):
    lead = db.get(Lead, lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(404, "Nao encontrado")
    if lead.status == body.status:
        return lead  # idempotente: repetir a mesma transicao nao e erro
    if not can_transition(lead.status, body.status):
        allowed = sorted(TRANSITIONS.get(lead.status, set()))
        raise HTTPException(409, f"Transicao invalida: {lead.status} -> {body.status}. Permitidas: {allowed}")
    previous, lead.status = lead.status, body.status
    audit.record(db, who, "transition", "leads", lead.id, {"from": previous, "to": body.status})
    db.commit()
    db.refresh(lead)
    return lead


interaction_router = build_crud_router(
    model=Interaction, prefix="/interactions", tag="interactions",
    create_schema=s.InteractionCreate, read_schema=s.InteractionRead,
    allow_delete=False, filters=("lead_id", "channel"),
)

conversation_router = build_crud_router(
    model=Conversation, prefix="/conversations", tag="conversations",
    create_schema=s.ConversationCreate, update_schema=s.ConversationUpdate,
    read_schema=s.ConversationRead, filters=("lead_id", "status"),
)

opportunity_router = build_crud_router(
    model=Opportunity, prefix="/opportunities", tag="opportunities",
    create_schema=s.OpportunityCreate, update_schema=s.OpportunityUpdate,
    read_schema=s.OpportunityRead, filters=("lead_id", "status"),
)

payment_router = build_crud_router(
    model=Payment, prefix="/payments", tag="payments",
    create_schema=s.PaymentCreate, update_schema=s.PaymentUpdate, read_schema=s.PaymentRead,
    allow_delete=False, filters=("opportunity_id", "status"),
)

routers: list[APIRouter] = [
    business_router, contact_router, lead_router, interaction_router,
    conversation_router, opportunity_router, payment_router,
]
