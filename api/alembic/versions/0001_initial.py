"""schema inicial (Parte 1)

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _deleted():
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def _fk(col, target):
    return sa.Column(col, sa.Uuid(), sa.ForeignKey(target), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        "users", _id(),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_ts(),
    )
    op.create_table(
        "businesses", _id(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("place_id", sa.String(255), unique=True, index=True),
        sa.Column("segment", sa.String(100), index=True),
        sa.Column("region", sa.String(100), index=True),
        sa.Column("address", sa.Text()),
        sa.Column("phone", sa.String(40)),
        sa.Column("phone_e164", sa.String(20), index=True),
        sa.Column("cnpj", sa.String(18)),
        sa.Column("website_url", sa.String(500)),
        sa.Column("has_website", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("dedupe_hash", sa.String(64), unique=True, index=True),
        *_ts(), _deleted(),
    )
    op.create_table(
        "contacts", _id(), _fk("business_id", "businesses.id"),
        sa.Column("name", sa.String(255)),
        sa.Column("role", sa.String(100)),
        sa.Column("phone", sa.String(40)),
        sa.Column("phone_e164", sa.String(20), index=True),
        sa.Column("email", sa.String(255), index=True),
        *_ts(), _deleted(),
    )
    op.create_table(
        "leads", _id(), _fk("business_id", "businesses.id"),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("score", sa.Integer()),
        sa.Column("tier", sa.String(1), index=True),
        sa.Column("score_version", sa.String(20)),
        sa.Column("score_breakdown", JSONType),
        sa.Column("justification", sa.Text()),
        *_ts(), _deleted(),
    )
    op.create_table(
        "interactions", _id(), _fk("lead_id", "leads.id"),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("external_id", sa.String(255), unique=True, index=True),
        sa.Column("meta", JSONType),
        *_ts(),
    )
    op.create_table(
        "conversations", _id(), _fk("lead_id", "leads.id"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=False),
        *_ts(), _deleted(),
    )
    op.create_table(
        "opportunities", _id(), _fk("lead_id", "leads.id"),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("value_cents", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("proposal_url", sa.String(500)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        *_ts(), _deleted(),
    )
    op.create_table(
        "payments", _id(), _fk("opportunity_id", "opportunities.id"),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50)),
        sa.Column("provider_ref", sa.String(255), unique=True, index=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True, index=True),
        *_ts(),
    )
    op.create_table(
        "consents", _id(),
        sa.Column("identifier", sa.String(255), nullable=False, index=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("basis", sa.String(30), nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Column("evidence", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
    )
    op.create_table(
        "suppression_list", _id(),
        sa.Column("identifier", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("source", sa.String(100)),
        *_ts(),
    )
    op.create_table(
        "audit_log", _id(),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("entity", sa.String(50), nullable=False, index=True),
        sa.Column("entity_id", sa.String(64), nullable=False, index=True),
        sa.Column("data", JSONType),
        *_ts(),
    )
    op.create_table(
        "outbox_events", _id(),
        sa.Column("topic", sa.String(100), nullable=False, index=True),
        sa.Column("payload", JSONType, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text()),
        *_ts(),
    )


def downgrade() -> None:
    for table in (
        "outbox_events", "audit_log", "suppression_list", "consents", "payments",
        "opportunities", "conversations", "interactions", "leads", "contacts",
        "businesses", "users",
    ):
        op.drop_table(table)
