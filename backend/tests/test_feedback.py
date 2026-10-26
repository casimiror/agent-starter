from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.models import Message, MessageFeedback
from app.services.feedback_service import FeedbackService, MessageNotRateableError

NOW = datetime(2026, 10, 24, tzinfo=UTC)


class FakeFeedbackRepository:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = {m.id: m for m in messages}
        self.ratings: dict[UUID, str] = {}

    def get_message(self, message_id):
        return self.messages.get(message_id)

    def set_rating(self, message_id, rating):
        self.ratings[message_id] = rating
        return MessageFeedback(
            id=uuid4(), message_id=message_id, rating=rating, created_at=NOW, updated_at=NOW
        )

    def clear_rating(self, message_id):
        return self.ratings.pop(message_id, None) is not None


def _message(role: str) -> Message:
    return Message(id=uuid4(), conversation_id=uuid4(), role=role, content="x", created_at=NOW)


@pytest.fixture
def setup():
    reply, question = _message("assistant"), _message("user")
    repo = FakeFeedbackRepository([reply, question])
    return FeedbackService(repo), repo, reply, question


def test_vote_can_be_changed_and_removed(setup):
    service, repo, reply, _ = setup
    service.rate(reply.id, "up")
    service.rate(reply.id, "down")
    assert repo.ratings == {reply.id: "down"}
    service.clear(reply.id)
    assert repo.ratings == {}


def test_clearing_without_a_vote_is_fine(setup):
    service, _, reply, _ = setup
    service.clear(reply.id)


@pytest.mark.parametrize("target", ["unknown", "user"])
def test_only_assistant_messages_can_be_rated(setup, target):
    service, repo, _, question = setup
    message_id = uuid4() if target == "unknown" else question.id
    with pytest.raises(MessageNotRateableError):
        service.rate(message_id, "up")
    with pytest.raises(MessageNotRateableError):
        service.clear(message_id)
    assert repo.ratings == {}
