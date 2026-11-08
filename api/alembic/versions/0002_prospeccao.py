"""prospeccao: sinais em businesses, prospecting_runs e api_usage (Parte 2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("businesses", sa.Column("website_status", sa.String(20)))
    op.add_column("businesses", sa.Column("rating", sa.Float()))
    op.add_column("businesses", sa.Column("reviews_count", sa.Integer()))
    op.add_column("businesses", sa.Column("places_cached_at", sa.DateTime(timezone=True)))

    op.create_table(
        "prospecting_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("segment", sa.String(100), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("text_query", sa.String(300), nullable=False),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("next_page_token", sa.Text()),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("found", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        *_ts(),
    )
    op.create_table(
        "api_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False, index=True),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("provider", "day", name="uq_api_usage_provider_day"),
    )


def downgrade() -> None:
    op.drop_table("api_usage")
    op.drop_table("prospecting_runs")
    for col in ("places_cached_at", "reviews_count", "rating", "website_status"):
        op.drop_column("businesses", col)
