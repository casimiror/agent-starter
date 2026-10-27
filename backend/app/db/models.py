"""ORM tables. Single source of truth for the schema: Alembic autogenerates from here."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampedMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConversationRow(TimestampedMixin, Base):
    """Anonymous: a visitor gets an id the first time they write."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "channel in ('web', 'whatsapp', 'voice')", name="conversations_channel_check"
        ),
        Index("conversations_visitor_channel_created_idx", "visitor_id", "channel", "created_at"),
    )

    # Anonymous browser id (UUID, never PII), the same value Langfuse gets as user_id. Null for
    # browsers without localStorage. On other channels it is a keyed hash of the sender.
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    # Where the conversation happens (docs/channels.md). The server default keeps an old app
    # version, which doesn't send it, working during a deploy and backfills existing rows as web.
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="web")


class MessageRow(TimestampedMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant')", name="messages_role_check"),
        Index("messages_conversation_created_idx", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class MessageFeedbackRow(TimestampedMixin, Base):
    """A visitor's 👍/👎 on one assistant message. Changing the vote updates the row; removing it
    deletes the row, so at most one row per message."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        CheckConstraint("rating in ('up', 'down')", name="message_feedback_rating_check"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
