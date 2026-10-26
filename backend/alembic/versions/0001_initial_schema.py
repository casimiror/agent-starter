"""initial schema: conversations, messages, message_feedback

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("conversations", "messages", "message_feedback")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "conversations",
        *_timestamps(),
        # Anonymous browser id, also the Langfuse user id. Never PII.
        sa.Column("visitor_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_index("ix_conversations_visitor_id", "conversations", ["visitor_id"])
    op.create_table(
        "messages",
        *_timestamps(),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.CheckConstraint("role in ('user', 'assistant')", name="messages_role_check"),
    )
    op.create_index(
        "messages_conversation_created_idx", "messages", ["conversation_id", "created_at"]
    )
    op.create_table(
        "message_feedback",
        *_timestamps(),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # one vote per message; changing it updates the row
        ),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rating in ('up', 'down')", name="message_feedback_rating_check"),
    )
    # Supabase exposes `public` through its REST API: RLS on with no policies means only the
    # backend (a direct Postgres connection as the table owner) can read or write these tables.
    # alembic_version is created by Alembic itself, outside any revision, so it is covered here.
    for table in (*TABLES, "alembic_version"):
        op.execute(f"alter table public.{table} enable row level security")


def downgrade() -> None:
    op.execute("alter table public.alembic_version disable row level security")
    op.drop_table("message_feedback")
    op.drop_index("messages_conversation_created_idx", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_visitor_id", table_name="conversations")
    op.drop_table("conversations")
