import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.models import Conversation
from app.services.channel_conversations import ChannelConversations

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
PHONE = "whatsapp:+34600123456"
WINDOW = timedelta(hours=24)


class FakeConversations:
    def __init__(self) -> None:
        self.latest: Conversation | None = None
        self.activity: datetime | None = None
        self.created: list[tuple] = []

    def latest_for_visitor(self, visitor_id, channel):
        return self.latest

    def get(self, conversation_id):
        return self.latest if self.latest and self.latest.id == conversation_id else None

    def last_activity(self, conversation_id):
        # Mirrors the repository: last message, else the conversation's creation time.
        return self.activity or (self.latest.created_at if self.latest else None)

    def get_or_create(self, conversation_id, visitor_id=None, channel="web"):
        self.created.append((conversation_id, visitor_id, channel))
        return Conversation(id=uuid4(), visitor_id=visitor_id, channel=channel, created_at=NOW)


def _service(conversations=None, secret="s3cret") -> ChannelConversations:
    return ChannelConversations(conversations or FakeConversations(), secret, WINDOW, lambda: NOW)


def _existing(conversations: FakeConversations, created_ago: timedelta = timedelta(hours=1)):
    conversations.latest = Conversation(
        id=uuid4(), visitor_id=uuid4(), channel="whatsapp", created_at=NOW - created_ago
    )
    return conversations.latest


def test_same_sender_gets_the_same_anonymous_id_and_it_hides_the_number():
    service = _service()
    visitor = service.visitor_id(PHONE)
    assert visitor == service.visitor_id(PHONE)
    assert visitor != service.visitor_id("whatsapp:+34600123457")
    assert "600123456" not in str(visitor)


def test_the_id_depends_on_the_secret():
    assert _service(secret="a").visitor_id(PHONE) != _service(secret="b").visitor_id(PHONE)


def test_a_fresh_conversation_is_reused():
    conversations = FakeConversations()
    latest = _existing(conversations)
    conversations.activity = NOW - timedelta(hours=23)

    assert _service(conversations).resolve(uuid4(), "whatsapp") == latest.id
    assert conversations.created == []


def test_a_conversation_idle_past_the_window_starts_a_new_one():
    conversations = FakeConversations()
    latest = _existing(conversations)
    conversations.activity = NOW - timedelta(hours=25)
    visitor = uuid4()

    resolved = _service(conversations).resolve(visitor, "whatsapp")

    assert resolved != latest.id
    assert conversations.created == [(None, visitor, "whatsapp")]


def test_without_messages_the_creation_time_counts():
    fresh, stale = FakeConversations(), FakeConversations()
    reused = _existing(fresh, created_ago=timedelta(hours=2))
    _existing(stale, created_ago=timedelta(hours=30))

    assert _service(fresh).resolve(uuid4(), "whatsapp") == reused.id
    _service(stale).resolve(uuid4(), "whatsapp")
    assert len(stale.created) == 1


def test_start_always_opens_a_new_conversation_even_inside_the_window():
    conversations = FakeConversations()
    latest = _existing(conversations)
    visitor = uuid4()

    started = _service(conversations).start(visitor, "voice")

    assert started != latest.id
    assert conversations.created == [(None, visitor, "voice")]


def test_find_returns_only_an_existing_conversation_of_that_channel():
    conversations = FakeConversations()
    existing = _existing(conversations)  # a whatsapp conversation
    service = _service(conversations)

    assert service.find(existing.id, "whatsapp") == existing
    assert service.find(existing.id, "voice") is None  # right id, wrong channel
    assert service.find(uuid4(), "whatsapp") is None  # unknown id


def test_a_visitor_without_conversations_gets_a_new_one_on_that_channel():
    conversations = FakeConversations()
    visitor = uuid4()
    _service(conversations).resolve(visitor, "voice")
    assert conversations.created == [(None, visitor, "voice")]


def _run_two_threads(service, first_key, second_key) -> int:
    """Max number of threads inside their lock at once."""
    inside, peak, guard = 0, 0, threading.Lock()

    def work(key):
        nonlocal inside, peak
        with service.lock(key):
            with guard:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.05)
            with guard:
                inside -= 1

    threads = [threading.Thread(target=work, args=(k,)) for k in (first_key, second_key)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return peak


def test_the_lock_serializes_the_same_visitor():
    visitor = uuid4()
    assert _run_two_threads(_service(), visitor, visitor) == 1


def test_the_lock_does_not_block_different_visitors():
    assert _run_two_threads(_service(), uuid4(), uuid4()) == 2


def test_locks_are_released_from_memory_when_nobody_waits():
    service = _service()
    visitor = uuid4()
    with service.lock(visitor):
        pass
    assert service._locks == {}


def test_turn_and_send_locks_are_independent_and_cleaned_up():
    service = _service()
    visitor = uuid4()
    with service.lock(visitor):
        with service.send_lock(visitor):  # hand over hand: both held at once
            assert len(service._locks) == 2
    assert service._locks == {}
