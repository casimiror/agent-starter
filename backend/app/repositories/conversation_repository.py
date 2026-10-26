from uuid import UUID

from app.db.daos.conversation_dao import ConversationDAO
from app.db.daos.message_dao import MessageDAO
from app.domain.models import Conversation, Message, Role


class ConversationRepository:
    def __init__(self, conversations: ConversationDAO, messages: MessageDAO) -> None:
        self._conversations = conversations
        self._messages = messages

    def get_or_create(
        self, conversation_id: UUID | None, visitor_id: UUID | None = None
    ) -> Conversation:
        """An existing conversation keeps the visitor it was created with."""
        if conversation_id and (row := self._conversations.get(conversation_id)):
            return Conversation.model_validate(row, from_attributes=True)
        row = self._conversations.insert(visitor_id=visitor_id)
        return Conversation.model_validate(row, from_attributes=True)

    def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        rows = self._messages.list_by("conversation_id", conversation_id, desc=True, limit=limit)
        return [Message.model_validate(r, from_attributes=True) for r in reversed(rows)]

    def append(self, conversation_id: UUID, role: Role, content: str) -> Message:
        row = self._messages.insert(conversation_id=conversation_id, role=role, content=content)
        return Message.model_validate(row, from_attributes=True)
