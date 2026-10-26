from uuid import UUID

from app.db.daos.message_dao import MessageDAO
from app.db.daos.message_feedback_dao import MessageFeedbackDAO
from app.domain.models import Message, MessageFeedback, Rating


class FeedbackRepository:
    def __init__(self, messages: MessageDAO, feedback: MessageFeedbackDAO) -> None:
        self._messages = messages
        self._feedback = feedback

    def get_message(self, message_id: UUID) -> Message | None:
        row = self._messages.get(message_id)
        return Message.model_validate(row, from_attributes=True) if row else None

    def set_rating(self, message_id: UUID, rating: Rating) -> MessageFeedback:
        row = self._feedback.upsert(message_id, rating)
        return MessageFeedback.model_validate(row, from_attributes=True)

    def clear_rating(self, message_id: UUID) -> bool:
        return self._feedback.delete_by_message(message_id)
