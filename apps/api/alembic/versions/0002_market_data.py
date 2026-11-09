"""Phase 2: price bars, latest quotes, signal snapshots, ticker fundamentals

Revision ID: 0002_market_data
Revises: 0001_initial
Create Date: Phase 2
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_market_data"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "latest_quotes",
        sa.Column("ticker_id", sa.UUID(), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=False),
        sa.Column("change", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=True),
        sa.Column(
            "change_percent", sa.Numeric(precision=12, scale=6, asdecimal=False), nullable=True
        ),
        sa.Column(
            "previous_close", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=True
        ),
        sa.Column("open", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=True),
        sa.Column("provider_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ticker_id"),
    )
    op.create_table(
        "price_bars",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticker_id", sa.UUID(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4, asdecimal=False), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker_id", "session_date", name="uq_price_bar_session"),
    )
    op.create_table(
        "signal_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticker_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=1, asdecimal=False), nullable=False),
        sa.Column("band", sa.String(length=20), nullable=False),
        sa.Column("formula_version", sa.Integer(), nullable=False),
        sa.Column("components_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signal_snapshots_ticker_computed",
        "signal_snapshots",
        ["ticker_id", "computed_at"],
        unique=False,
    )
    op.add_column(
        "tickers",
        sa.Column("market_cap", sa.Numeric(precision=20, scale=0, asdecimal=False), nullable=True),
    )
    op.add_column(
        "tickers", sa.Column("profile_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tickers", "profile_updated_at")
    op.drop_column("tickers", "market_cap")
    op.drop_index("ix_signal_snapshots_ticker_computed", table_name="signal_snapshots")
    op.drop_table("signal_snapshots")
    op.drop_table("price_bars")
    op.drop_table("latest_quotes")
