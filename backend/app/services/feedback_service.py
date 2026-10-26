from uuid import UUID

from app.domain.models import MessageFeedback, Rating
from app.repositories.feedback_repository import FeedbackRepository


class MessageNotRateableError(Exception):
    """The id is not an assistant message (unknown id, or a user's own message)."""


class FeedbackService:
    """A visitor's 👍/👎 on the bot's replies, kept for analysing conversations."""

    def __init__(self, feedback: FeedbackRepository) -> None:
        self._feedback = feedback

    def rate(self, message_id: UUID, rating: Rating) -> MessageFeedback:
        self._ensure_rateable(message_id)
        return self._feedback.set_rating(message_id, rating)

    def clear(self, message_id: UUID) -> None:
        """Idempotent: clearing a message with no vote is fine."""
        self._ensure_rateable(message_id)
        self._feedback.clear_rating(message_id)

    def _ensure_rateable(self, message_id: UUID) -> None:
        message = self._feedback.get_message(message_id)
        if message is None or message.role != "assistant":
            raise MessageNotRateableError(message_id)
