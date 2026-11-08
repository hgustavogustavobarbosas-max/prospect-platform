"""Modelos do dominio. Escrita sempre via API (os defaults vivem na aplicacao)."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, SoftDeleteMixin, TimestampMixin
from app.db.types import EncryptedJSON, EncryptedText


def _now() -> datetime:
    return datetime.now(UTC)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="operator")  # admin|operator
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Business(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "businesses"
    name: Mapped[str] = mapped_column(String(255))
    place_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    segment: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(100), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)
    cnpj: Mapped[str | None] = mapped_column(String(18))
    website_url: Mapped[str | None] = mapped_column(String(500))
    has_website: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # Parte 2: sinais de qualificacao. rating/reviews/places_cached_at so no modo permissive.
    website_status: Mapped[str | None] = mapped_column(String(20))  # none|social|site_ok|site_down|unchecked
    rating: Mapped[float | None] = mapped_column(Float)
    reviews_count: Mapped[int | None] = mapped_column(Integer)
    places_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contact(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "contacts"
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), index=True
    )
    name: Mapped[str | None] = mapped_column(EncryptedText)
    role: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(EncryptedText)
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)  # busca: fica em claro
    email: Mapped[str | None] = mapped_column(EncryptedText)


class Lead(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "leads"
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    tier: Mapped[str | None] = mapped_column(String(1), index=True)
    score_version: Mapped[str | None] = mapped_column(String(20))
    score_breakdown: Mapped[dict | None] = mapped_column(JSONType)
    justification: Mapped[str | None] = mapped_column(Text)


class Interaction(IdMixin, TimestampMixin, Base):
    """Append-only. `external_id` (ex.: wamid do WhatsApp) garante idempotencia de webhooks."""

    __tablename__ = "interactions"
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(3))  # in|out
    content: Mapped[str | None] = mapped_column(EncryptedText)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    meta: Mapped[dict | None] = mapped_column(JSONType)


class Conversation(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "conversations"
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|handoff|closed
    summary: Mapped[str | None] = mapped_column(Text)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)  # 1e-6 USD, evita float
    qualification: Mapped[dict | None] = mapped_column(JSONType)  # dados coletados pelo agente


class Opportunity(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "opportunities"
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id"), index=True)
    plan: Mapped[str] = mapped_column(String(20))  # basic|professional|custom
    value_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    proposal_url: Mapped[str | None] = mapped_column(String(500))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proposal_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_via: Mapped[str | None] = mapped_column(String(30))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nps_score: Mapped[int | None] = mapped_column(Integer)
    nps_comment: Mapped[str | None] = mapped_column(EncryptedText)
    client_name: Mapped[str | None] = mapped_column(EncryptedText)
    proposal_notes: Mapped[str | None] = mapped_column(EncryptedText)


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_ref: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("subscriptions.id"))


class Consent(IdMixin, TimestampMixin, Base):
    """Registro append-only de consentimento. O estado vigente e o ultimo por (identifier, channel)."""

    __tablename__ = "consents"
    identifier: Mapped[str] = mapped_column(String(255), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10))  # granted|revoked
    basis: Mapped[str] = mapped_column(String(30))  # opt_in|legitimate_interest|contract
    source: Mapped[str | None] = mapped_column(String(100))
    evidence: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SuppressionEntry(IdMixin, TimestampMixin, Base):
    """Lista de supressao: ninguem aqui recebe contato, em nenhum canal."""

    __tablename__ = "suppression_list"
    identifier: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(50))  # opt_out|complaint|manual|bounce
    source: Mapped[str | None] = mapped_column(String(100))


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    actor: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict | None] = mapped_column(JSONType)  # sem PII: apenas nomes de campos


class OutboxEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "outbox_events"
    topic: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_now
    )
    last_error: Mapped[str | None] = mapped_column(Text)


class ProspectingRun(IdMixin, TimestampMixin, Base):
    """Uma busca paginada e retomavel (guarda o nextPageToken)."""

    __tablename__ = "prospecting_runs"
    segment: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(100))
    text_query: Mapped[str] = mapped_column(String(300))
    page_size: Mapped[int] = mapped_column(Integer, default=20)
    status: Mapped[str] = mapped_column(String(20), default="partial", index=True)
    next_page_token: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ApiUsage(IdMixin, TimestampMixin, Base):
    """Consumo diario por provedor (orcamento de quota e custo)."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_api_usage_provider_day"),)
    provider: Mapped[str] = mapped_column(String(30), index=True)  # places|llm
    day: Mapped[date] = mapped_column(Date, index=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)


class Plan(IdMixin, TimestampMixin, Base):
    """Catalogo: o agente le precos SOMENTE daqui (nunca do prompt)."""

    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # basic|professional|custom
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    price_cents: Mapped[int | None] = mapped_column(Integer)  # None = sob consulta
    features: Mapped[list | None] = mapped_column(JSONType)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SystemFlag(TimestampMixin, Base):
    """Chaves globais (ex.: sending_enabled = kill switch de envios)."""

    __tablename__ = "system_flags"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(255))


class Briefing(IdMixin, TimestampMixin, Base):
    """Formulario do cliente para montar o site. Dados cifrados em repouso."""

    __tablename__ = "briefings"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), unique=True, index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|submitted
    data: Mapped[dict | None] = mapped_column(EncryptedJSON)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Preview(IdMixin, TimestampMixin, Base):
    __tablename__ = "previews"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|expired
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    html: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[list | None] = mapped_column(JSONType)


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), index=True
    )
    plan_code: Mapped[str] = mapped_column(String(30))  # maintenance|digital_catalog|scheduling
    price_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    next_billing_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Site(IdMixin, TimestampMixin, Base):
    """Site entregue, monitorado por uptime."""

    __tablename__ = "sites"
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="unknown")  # unknown|up|down
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticket(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tickets"
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("opportunities.id"), index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("leads.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
