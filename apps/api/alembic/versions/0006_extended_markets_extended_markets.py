"""Extended markets: the earnings calendar table (Phase 5).

The wider ticker universe needs no migration - it is reference data, seeded as
`tickers` rows by `app.db.seed`, so adding or retiring a name is a seed run
rather than a schema change.

Revision ID: 0006_extended_markets
Revises: 0005_chat
Create Date: 2026-10-26 21:45:19.797634
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_extended_markets"
down_revision: str | None = "0005_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "earnings_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("ticker_id", sa.UUID(), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("timing", sa.String(length=8), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("eps_estimate", sa.Float(), nullable=True),
        sa.Column("eps_actual", sa.Float(), nullable=True),
        sa.Column("revenue_estimate", sa.Float(), nullable=True),
        sa.Column("revenue_actual", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "session_date", name="uq_earnings_symbol_date"),
    )
    op.create_index("ix_earnings_session_date", "earnings_events", ["session_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_earnings_session_date", table_name="earnings_events")
    op.drop_table("earnings_events")
