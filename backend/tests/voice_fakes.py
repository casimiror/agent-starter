"""Fakes shared by the voice tests: an in-memory conversation store and a scripted chat."""

import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.domain.models import Conversation
from app.services.channel_conversations import ChannelConversations
from app.services.voice_service import VoiceService

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
TOKEN = "twilio-token"
BASE = "https://bot.example.com"
CALLER = "+34600123456"
CALLER_NAME = "Jane Doe"


def make_settings(**values) -> Settings:
    values.setdefault("channels", ["web", "voice"])
    return Settings(
        _env_file=None,
        channel_id_secret="s",
        public_base_url=values.pop("public_base_url", BASE),
        twilio_auth_token=TOKEN,
        **values,
    )


class FakeConversations:
    def __init__(self) -> None:
        self.rows: dict = {}

    def get(self, conversation_id):
        return self.rows.get(conversation_id)

    def latest_for_visitor(self, visitor_id, channel):
        raise AssertionError("voice must not reuse a conversation")

    def last_activity(self, conversation_id):
        raise AssertionError("voice must not reuse a conversation")

    def get_or_create(self, conversation_id, visitor_id=None, channel="web"):
        row = Conversation(id=uuid4(), visitor_id=visitor_id, channel=channel, created_at=NOW)
        self.rows[row.id] = row
        return row


class FakeChat:
    def __init__(
        self, reply="All good", error: Exception | None = None, delay: float = 0.0
    ) -> None:
        self.reply = reply
        self.error = error
        self.delay = delay
        self.calls: list[tuple] = []
        self.max_concurrent = 0
        self._running = 0
        self._guard = threading.Lock()

    def handle_turn(self, conversation_id, user_text, visitor_id=None, channel="web"):
        with self._guard:
            self._running += 1
            self.max_concurrent = max(self.max_concurrent, self._running)
        try:
            self.calls.append((conversation_id, user_text, visitor_id, channel))
            time.sleep(self.delay)
            if self.error:
                raise self.error
            return SimpleNamespace(reply=self.reply)
        finally:
            with self._guard:
                self._running -= 1


class Clock:
    """A settable clock for both datetime and monotonic uses."""

    def __init__(self) -> None:
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return NOW + timedelta(seconds=self.elapsed)


def make_voice(chat=None, hit=None, rate_limit="5/minute", max_call_seconds=600, clock=None):
    repo = FakeConversations()
    channels = ChannelConversations(repo, "s3cret", timedelta(hours=24), lambda: NOW)
    chat = chat or FakeChat()
    clock = clock or Clock()
    flushed: list[int] = []
    service = VoiceService(
        channels,
        chat,
        rate_limit,
        "No links aloud.",
        max_call_seconds,
        hit=hit or (lambda *_: True),
        flush=lambda: flushed.append(1),
        now=clock.now,
    )
    return SimpleNamespace(
        service=service, chat=chat, repo=repo, channels=channels, flushed=flushed, clock=clock
    )
