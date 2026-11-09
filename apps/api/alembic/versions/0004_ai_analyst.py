"""AI analyst: article embeddings and the message ledger.

Revision ID: 0004_ai_analyst
Revises: 0003_news_feed
Create Date: 2026-10-19 21:50:37.654450
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_ai_analyst"
down_revision: str | None = "0003_news_feed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The image is pgvector/pgvector:pg16; on plain postgres:16 this fails here
    # rather than silently leaving the analyst unable to retrieve anything.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("retrieved", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_message_user_created", "ai_messages", ["user_id", "created_at"], unique=False
    )

    op.add_column(
        "feed_items",
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1536), nullable=True),
    )
    op.add_column("feed_items", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feed_items", sa.Column("embedding_model", sa.String(length=64), nullable=True))

    # HNSW over cosine distance, matching the `<=>` operator the retrieval query
    # uses. Built on an empty column, so it costs nothing now; without it every
    # question would scan every article once the feed grows.
    op.execute(
        "CREATE INDEX ix_feed_item_embedding ON feed_items "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_feed_item_embedding")
    op.drop_column("feed_items", "embedding_model")
    op.drop_column("feed_items", "embedded_at")
    op.drop_column("feed_items", "embedding")
    op.drop_index("ix_ai_message_user_created", table_name="ai_messages")
    op.drop_table("ai_messages")
    # The extension is left in place: dropping it would break any other schema
    # in the same database that happens to use vector columns.
