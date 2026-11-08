"""fechamento, entrega e pos-venda; criptografia de campos (Parte 4)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _fk(col, target, nullable=False, unique=False):
    return sa.Column(col, sa.Uuid(), sa.ForeignKey(target), nullable=nullable, unique=unique, index=True)


def upgrade() -> None:
    # contatos: campos pessoais passam a ser cifrados (Text). O indice de e-mail deixa de fazer sentido.
    op.drop_index("ix_contacts_email", table_name="contacts")
    for col in ("name", "phone", "email"):
        op.alter_column("contacts", col, type_=sa.Text(), existing_type=sa.String(255), existing_nullable=True)

    for name, typ in [
        ("proposal_token", sa.String(64)), ("accepted_at", sa.DateTime(timezone=True)),
        ("accepted_via", sa.String(30)), ("delivered_at", sa.DateTime(timezone=True)),
        ("nps_score", sa.Integer()), ("nps_comment", sa.Text()),
        ("client_name", sa.Text()), ("proposal_notes", sa.Text()),
    ]:
        op.add_column("opportunities", sa.Column(name, typ))
    op.create_index("ix_opportunities_proposal_token", "opportunities", ["proposal_token"], unique=True)

    op.create_table(
        "briefings", sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("opportunity_id", "opportunities.id", unique=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("data", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        *_ts(),
    )
    op.create_table(
        "previews", sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("opportunity_id", "opportunities.id"),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("html", sa.Text()),
        sa.Column("feedback", JSONType),
        *_ts(),
    )
    op.create_table(
        "subscriptions", sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("opportunity_id", "opportunities.id"),
        sa.Column("plan_code", sa.String(30), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
    )
    op.create_table(
        "sites", sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("opportunity_id", "opportunities.id"),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        *_ts(),
    )
    op.create_table(
        "tickets", sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("opportunity_id", "opportunities.id", nullable=True),
        _fk("lead_id", "leads.id", nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("priority", sa.String(10), nullable=False),
        *_ts(), sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.add_column("payments", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("paid_at", sa.DateTime(timezone=True)))
    op.add_column("payments", sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id")))


def downgrade() -> None:
    for col in ("subscription_id", "paid_at", "due_at"):
        op.drop_column("payments", col)
    for t in ("tickets", "sites", "subscriptions", "previews", "briefings"):
        op.drop_table(t)
    op.drop_index("ix_opportunities_proposal_token", table_name="opportunities")
    for col in ("proposal_notes", "client_name", "nps_comment", "nps_score", "delivered_at", "accepted_via", "accepted_at", "proposal_token"):
        op.drop_column("opportunities", col)
    for col in ("email", "phone", "name"):
        op.alter_column("contacts", col, type_=sa.String(255), existing_type=sa.Text(), existing_nullable=True)
    op.create_index("ix_contacts_email", "contacts", ["email"])
