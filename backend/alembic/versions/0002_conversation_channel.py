"""conversations.channel: where the conversation happens (web, whatsapp, voice)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The server default keeps the previous app version (which doesn't send channel) working
    # during a deploy and backfills existing rows as web. RLS is already on for this table (0001).
    op.add_column(
        "conversations",
        sa.Column("channel", sa.String(16), server_default="web", nullable=False),
    )
    op.create_check_constraint(
        "conversations_channel_check",
        "conversations",
        "channel in ('web', 'whatsapp', 'voice')",
    )
    op.create_index(
        "conversations_visitor_channel_created_idx",
        "conversations",
        ["visitor_id", "channel", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("conversations_visitor_channel_created_idx", table_name="conversations")
    op.drop_constraint("conversations_channel_check", "conversations", type_="check")
    op.drop_column("conversations", "channel")
