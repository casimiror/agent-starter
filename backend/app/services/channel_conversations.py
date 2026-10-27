import hashlib
import hmac
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from app.domain.models import Channel, Conversation
from app.repositories.conversation_repository import ConversationRepository

# Namespace for the visitor ids; any fixed UUID works, the secret is what protects the sender.
_SENDER_NAMESPACE = UUID("6f1d2c1e-8a47-4b0e-9d52-3c0f7d6a1b11")


class ChannelConversations:
    """What every non-web channel needs before it calls `ChatService.handle_turn`: an anonymous
    id for the sender and the conversation to continue. No HTTP, no provider code."""

    def __init__(
        self,
        conversations: ConversationRepository,
        id_secret: str,
        window: timedelta,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conversations = conversations
        self._id_secret = id_secret.encode()
        self._window = window
        self._now = now
        # Per process, not global: see `lock`.
        self._locks: dict[tuple[UUID, str], tuple[threading.Lock, int]] = {}
        self._locks_guard = threading.Lock()

    def visitor_id(self, sender: str) -> UUID:
        """Stable anonymous id for a phone number or call id. The sender is never stored or
        logged: the keyed hash can't be reversed or recomputed without CHANNEL_ID_SECRET (so
        rotating the secret gives every sender a new id)."""
        digest = hmac.new(self._id_secret, sender.encode(), hashlib.sha256).hexdigest()
        return uuid5(_SENDER_NAMESPACE, digest)

    def resolve(self, visitor_id: UUID, channel: Channel) -> UUID:
        """The visitor's latest conversation on this channel while it is fresh, else a new one.

        Fresh means the last message (or, with none yet, the creation) is within the window."""
        latest = self._conversations.latest_for_visitor(visitor_id, channel)
        if latest:
            last = self._conversations.last_activity(latest.id)
            if last and self._now() - last < self._window:
                return latest.id
        return self._conversations.get_or_create(None, visitor_id, channel).id

    def start(self, visitor_id: UUID, channel: Channel) -> UUID:
        """Always a new conversation, for channels where the unit is not a time window: a phone
        call is one conversation, however soon the same caller rings again."""
        return self._conversations.get_or_create(None, visitor_id, channel).id

    def find(self, conversation_id: UUID, channel: Channel) -> Conversation | None:
        """An existing conversation of this channel, else None. For ids that come back from the
        provider (a URL, a TwiML parameter): never trust that they point at a real, right-channel
        conversation, because `handle_turn` would silently open a new one for an unknown id."""
        found = self._conversations.get(conversation_id)
        return found if found and found.channel == channel else None

    def record_heard(self, conversation_id: UUID, heard: str) -> None:
        """A spoken reply was cut short: keep only what the caller heard as the assistant's
        message, so the next turn does not assume the whole reply was said. When the reply is not
        stored yet (the last message is not the assistant's), store the heard part instead."""
        if not self._conversations.replace_last_assistant(conversation_id, heard):
            self._conversations.append(conversation_id, "assistant", heard)

    @contextmanager
    def lock(self, visitor_id: UUID) -> Iterator[None]:
        """Hold around `resolve` + the turn, so two quick messages from one sender don't both
        find no fresh conversation and open two.

        The lock lives in this process: it protects a single worker (local dev, one container).
        With several workers or Vercel instances two messages can still race; closing that needs
        a database lock (advisory lock) or a unique "open conversation" row per sender."""
        with self._hold((visitor_id, "turn")):
            yield

    @contextmanager
    def send_lock(self, visitor_id: UUID) -> Iterator[None]:
        """Keeps one sender's replies in order while `lock` is already free for the next turn.

        Hand over hand: take this lock while still holding `lock`, then release `lock` and send.
        A slow provider then delays only that sender's later replies, not their next LLM turn,
        and a reply can't overtake the one before it."""
        with self._hold((visitor_id, "send")):
            yield

    @contextmanager
    def _hold(self, key: tuple[UUID, str]) -> Iterator[None]:
        with self._locks_guard:
            entry, users = self._locks.get(key, (threading.Lock(), 0))
            self._locks[key] = (entry, users + 1)
        try:
            with entry:
                yield
        finally:
            with self._locks_guard:
                _, users = self._locks[key]
                if users == 1:
                    del self._locks[key]  # no waiters left: don't keep one lock per sender
                else:
                    self._locks[key] = (entry, users - 1)
