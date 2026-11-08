import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Channel = Literal["whatsapp", "email", "phone", "web"]
LeadStatus = Literal[
    "new", "qualified", "contacted", "replying", "handoff", "won", "lost", "suppressed"
]
Plan = Literal["basic", "professional", "custom"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Stamped(ORM):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------- auth ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    role: Literal["admin", "operator"] = "operator"


class UserRead(Stamped):
    email: EmailStr
    role: str
    is_active: bool


# ---------- business ----------
class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    place_id: str | None = None
    segment: str | None = None
    region: str | None = None
    address: str | None = None
    phone: str | None = None
    cnpj: str | None = None
    website_url: str | None = None
    source: str = "manual"


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    segment: str | None = None
    region: str | None = None
    address: str | None = None
    phone: str | None = None
    cnpj: str | None = None
    website_url: str | None = None


class BusinessRead(Stamped):
    name: str
    place_id: str | None
    segment: str | None
    region: str | None
    address: str | None
    phone: str | None
    phone_e164: str | None
    cnpj: str | None
    website_url: str | None
    has_website: bool
    source: str
    dedupe_hash: str | None
    website_status: str | None = None
    rating: float | None = None
    reviews_count: int | None = None
    places_cached_at: datetime | None = None


# ---------- contact ----------
class ContactCreate(BaseModel):
    business_id: uuid.UUID
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class ContactUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class ContactRead(Stamped):
    business_id: uuid.UUID
    name: str | None
    role: str | None
    phone: str | None
    phone_e164: str | None
    email: str | None


# ---------- lead ----------
class LeadCreate(BaseModel):
    business_id: uuid.UUID
    score: int | None = Field(default=None, ge=0, le=100)
    tier: Literal["A", "B", "C"] | None = None
    score_version: str | None = None
    score_breakdown: dict[str, Any] | None = None
    justification: str | None = None


class LeadUpdate(BaseModel):
    score: int | None = Field(default=None, ge=0, le=100)
    tier: Literal["A", "B", "C"] | None = None
    score_version: str | None = None
    score_breakdown: dict[str, Any] | None = None
    justification: str | None = None


class LeadRead(Stamped):
    business_id: uuid.UUID
    status: str
    score: int | None
    tier: str | None
    score_version: str | None
    score_breakdown: dict[str, Any] | None
    justification: str | None


class LeadStatusChange(BaseModel):
    status: LeadStatus


# ---------- interaction ----------
class InteractionCreate(BaseModel):
    lead_id: uuid.UUID
    channel: Channel
    direction: Literal["in", "out"]
    content: str | None = None
    external_id: str | None = Field(default=None, max_length=255)
    meta: dict[str, Any] | None = None


class InteractionRead(Stamped):
    lead_id: uuid.UUID
    channel: str
    direction: str
    content: str | None
    external_id: str | None
    meta: dict[str, Any] | None


# ---------- conversation ----------
class ConversationCreate(BaseModel):
    lead_id: uuid.UUID
    summary: str | None = None


class ConversationUpdate(BaseModel):
    status: Literal["open", "handoff", "closed"] | None = None
    summary: str | None = None
    tokens_used: int | None = Field(default=None, ge=0)
    cost_micro_usd: int | None = Field(default=None, ge=0)


class ConversationRead(Stamped):
    lead_id: uuid.UUID
    status: str
    summary: str | None
    tokens_used: int
    cost_micro_usd: int


# ---------- opportunity / payment ----------
class OpportunityCreate(BaseModel):
    lead_id: uuid.UUID
    plan: Plan
    value_cents: int | None = Field(default=None, ge=0)
    proposal_url: str | None = None
    valid_until: datetime | None = None


class OpportunityUpdate(BaseModel):
    plan: Plan | None = None
    value_cents: int | None = Field(default=None, ge=0)
    status: Literal["draft", "sent", "accepted", "rejected", "expired", "delivered"] | None = None
    proposal_url: str | None = None
    valid_until: datetime | None = None


class OpportunityRead(Stamped):
    lead_id: uuid.UUID
    plan: str
    value_cents: int | None
    status: str
    proposal_url: str | None
    valid_until: datetime | None
    accepted_at: datetime | None = None
    delivered_at: datetime | None = None
    nps_score: int | None = None


class PaymentCreate(BaseModel):
    opportunity_id: uuid.UUID
    amount_cents: int = Field(ge=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    provider: str | None = None
    provider_ref: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=255)


class PaymentUpdate(BaseModel):
    status: Literal["pending", "paid", "failed", "refunded", "overdue"] | None = None
    provider_ref: str | None = None


class PaymentRead(Stamped):
    opportunity_id: uuid.UUID
    amount_cents: int
    currency: str
    status: str
    provider: str | None
    provider_ref: str | None
    idempotency_key: str


# ---------- compliance ----------
class ConsentCreate(BaseModel):
    identifier: str
    channel: Channel
    status: Literal["granted", "revoked"]
    basis: Literal["opt_in", "legitimate_interest", "contract"] = "opt_in"
    source: str | None = None
    evidence: str | None = None


class ConsentRead(Stamped):
    identifier: str
    channel: str
    status: str
    basis: str
    source: str | None
    occurred_at: datetime


class SuppressionCreate(BaseModel):
    identifier: str
    reason: Literal["opt_out", "complaint", "manual", "bounce"] = "manual"
    source: str | None = None


class SuppressionRead(Stamped):
    identifier: str
    reason: str
    source: str | None


class CanContactOut(BaseModel):
    identifier: str
    channel: str
    allowed: bool
    reason: str


# ---------- outbox ----------
class OutboxCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=8, max_length=255)


class OutboxAck(BaseModel):
    success: bool
    error: str | None = None


class OutboxRead(Stamped):
    topic: str
    payload: dict[str, Any]
    idempotency_key: str
    status: str
    attempts: int
    available_at: datetime
    last_error: str | None


# ---------- prospeccao ----------
class RunCreate(BaseModel):
    segment: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=100)
    text_query: str | None = Field(default=None, max_length=300)
    max_pages: int = Field(default=1, ge=1, le=3)
    page_size: int = Field(default=20, ge=1, le=20)


class RunContinue(BaseModel):
    max_pages: int = Field(default=1, ge=1, le=3)


class RunRead(Stamped):
    segment: str
    region: str
    text_query: str
    page_size: int
    status: str
    pages: int
    found: int
    created: int
    duplicates: int
    error: str | None
    next_page_token: str | None


class UsageRead(ORM):
    provider: str
    day: date
    calls: int
    tokens: int
    cost_micro_usd: int


class LiveDetails(ORM):
    place_id: str
    name: str | None
    address: str | None
    phone: str | None
    website: str | None
    rating: float | None
    reviews: int | None
    business_status: str | None


# ---------- Parte 3: catalogo, flags, agente ----------
class PlanCreate(BaseModel):
    code: Literal["basic", "professional", "custom", "maintenance", "digital_catalog", "scheduling"]
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    features: list[str] | None = None
    active: bool = True


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    features: list[str] | None = None
    active: bool | None = None


class PlanRead(Stamped):
    code: str
    name: str
    description: str | None
    price_cents: int | None
    features: list[str] | None
    active: bool


class FlagSet(BaseModel):
    value: bool


class FlagRead(ORM):
    key: str
    value: bool
    updated_by: str | None


class AgentIn(BaseModel):
    lead_id: uuid.UUID
    text: str = Field(default="", max_length=4000)
    external_id: str = Field(min_length=1, max_length=255)  # ex.: wamid
    message_type: Literal["text", "audio", "image", "document", "other"] = "text"
    from_phone: str | None = Field(default=None, max_length=40)


class AgentOut(BaseModel):
    action: Literal["reply", "handoff", "optout", "blocked", "human_active", "duplicate"]
    reply: str | None = None
    conversation_id: uuid.UUID | None = None
    outbox_id: uuid.UUID | None = None
    flags: list[str] = []


class FollowupDue(BaseModel):
    lead_id: uuid.UUID
    attempt: int
    template: str
    idempotency_key: str


# ---------- Parte 4 ----------
class ProposalIn(BaseModel):
    client_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class ProposalOut(BaseModel):
    url: str
    pdf_url: str
    valid_until: datetime


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class DeliverIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    domain: str | None = Field(default=None, max_length=200)


class ChargeIn(BaseModel):
    amount_cents: int | None = Field(default=None, ge=1)
    due_in_days: int = Field(default=3, ge=0, le=60)
    provider: str = "manual"


class SubscriptionIn(BaseModel):
    plan_code: Literal["maintenance", "digital_catalog", "scheduling"]
    price_cents: int | None = Field(default=None, ge=1)


class SubscriptionRead(Stamped):
    opportunity_id: uuid.UUID
    plan_code: str
    price_cents: int
    status: str
    next_billing_at: datetime


class TicketCreate(BaseModel):
    opportunity_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    priority: Literal["low", "normal", "high"] = "normal"


class TicketUpdate(BaseModel):
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "in_progress", "resolved"] | None = None
    priority: Literal["low", "normal", "high"] | None = None


class TicketRead(Stamped):
    opportunity_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    subject: str
    body: str | None
    status: str
    priority: str


class SiteRead(Stamped):
    opportunity_id: uuid.UUID
    url: str
    status: str
    consecutive_failures: int
    last_check_at: datetime | None


class EraseIn(BaseModel):
    identifier: str
    confirm: bool
