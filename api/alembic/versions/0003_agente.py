"""agente comercial: plans, system_flags, conversations.qualification (Parte 3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("conversations", sa.Column("qualification", JSONType))
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("price_cents", sa.Integer()),
        sa.Column("features", JSONType),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_ts(),
    )
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(255)),
        *_ts(),
    )


def downgrade() -> None:
    op.drop_table("system_flags")
    op.drop_table("plans")
    op.drop_column("conversations", "qualification")
