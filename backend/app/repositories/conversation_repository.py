from datetime import datetime
from uuid import UUID

from app.db.daos.conversation_dao import ConversationDAO
from app.db.daos.message_dao import MessageDAO
from app.domain.models import Channel, Conversation, Message, Role


class ConversationRepository:
    def __init__(self, conversations: ConversationDAO, messages: MessageDAO) -> None:
        self._conversations = conversations
        self._messages = messages

    def get_or_create(
        self,
        conversation_id: UUID | None,
        visitor_id: UUID | None = None,
        channel: Channel = "web",
    ) -> Conversation:
        """An existing conversation keeps the visitor and channel it was created with."""
        if conversation_id and (row := self._conversations.get(conversation_id)):
            return Conversation.model_validate(row, from_attributes=True)
        row = self._conversations.insert(visitor_id=visitor_id, channel=channel)
        return Conversation.model_validate(row, from_attributes=True)

    def get(self, conversation_id: UUID) -> Conversation | None:
        row = self._conversations.get(conversation_id)
        return Conversation.model_validate(row, from_attributes=True) if row else None

    def latest_for_visitor(self, visitor_id: UUID, channel: Channel) -> Conversation | None:
        row = self._conversations.latest_for_visitor(visitor_id, channel)
        return Conversation.model_validate(row, from_attributes=True) if row else None

    def last_activity(self, conversation_id: UUID) -> datetime | None:
        """Time of the last message; an empty conversation counts from when it was created.
        None only if the conversation does not exist."""
        rows = self._messages.list_by("conversation_id", conversation_id, desc=True, limit=1)
        if rows:
            return rows[0].created_at
        row = self._conversations.get(conversation_id)
        return row.created_at if row else None

    def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        rows = self._messages.list_by("conversation_id", conversation_id, desc=True, limit=limit)
        return [Message.model_validate(r, from_attributes=True) for r in reversed(rows)]

    def append(self, conversation_id: UUID, role: Role, content: str) -> Message:
        row = self._messages.insert(conversation_id=conversation_id, role=role, content=content)
        return Message.model_validate(row, from_attributes=True)

    def replace_last_assistant(self, conversation_id: UUID, content: str) -> bool:
        """Overwrite the text of the conversation's last message when it is the assistant's (the
        reply a caller cut short); False when the last message is the user's or there is none."""
        rows = self._messages.list_by("conversation_id", conversation_id, desc=True, limit=1)
        if not rows or rows[0].role != "assistant":
            return False
        return self._messages.set_content(rows[0].id, content)
