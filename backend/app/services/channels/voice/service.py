import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core import observability
from app.core.rate_limit import hit_sender
from app.services.channels.conversations import ChannelConversations
from app.services.channels.voice.format import format_for_speech
from app.services.chat_service import ChatService

log = logging.getLogger("app.voice")

APOLOGY = "Sorry, something went wrong on my side. Could you say that again?"
NO_ANSWER = "Sorry, I don't have an answer for that."


@dataclass(frozen=True)
class VoiceCall:
    """One phone call = one conversation. Holds ids only, never the caller's number."""

    visitor_id: UUID
    conversation_id: UUID
    started_at: datetime


class VoiceService:
    """What the voice modes share: admit a call, find it again, answer one turn in speech. No
    HTTP, no TwiML, no WebSocket: the routes and the relay session wrap it."""

    def __init__(
        self,
        channels: ChannelConversations,
        chat: ChatService,
        rate_limit: str,
        link_phrase: str,
        max_call_seconds: int,
        hit: Callable[[str, str, str], bool] = hit_sender,
        flush: Callable[[], None] = observability.flush,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._channels = channels
        self._chat = chat
        self._rate_limit = rate_limit
        self._link_phrase = link_phrase
        self._max_call = timedelta(seconds=max_call_seconds)
        self._hit = hit
        self._flush = flush
        self._now = now

    def start_call(self, caller: str, call_sid: str) -> VoiceCall | None:
        """Admit a new call: None when this caller is over `RATE_LIMIT_VOICE`.

        `caller` is Twilio's `From` (personal data): it only goes into the keyed hash. Each call is
        a new conversation, unlike WhatsApp, which reuses one inside a 24 h window: a call has a
        natural start and end, and the next call should not inherit the last one's context."""
        visitor_id = self._channels.visitor_id(caller)
        fields = {"visitor_id": str(visitor_id), "call_sid": call_sid}
        if not self._hit(self._rate_limit, "voice", str(visitor_id)):
            log.warning("voice caller over the limit", extra=fields)
            return None
        conversation_id = self._channels.start(visitor_id, "voice")
        log.info("voice call started", extra={**fields, "conversation_id": str(conversation_id)})
        return VoiceCall(visitor_id, conversation_id, self._now())

    def find_call(self, conversation_id: UUID) -> VoiceCall | None:
        """The call a conversation id (from a URL or a parameter) belongs to, or None when it
        isn't an existing voice conversation."""
        conversation = self._channels.find(conversation_id, "voice")
        if not conversation or not conversation.visitor_id:
            return None
        return VoiceCall(conversation.visitor_id, conversation.id, conversation.created_at)

    def record_heard(self, call: VoiceCall, heard: str, call_sid: str = "") -> None:
        """The caller interrupted a reply: store the part they heard instead of the whole reply.
        Never raises (it runs beside a live call); blocking, call it from a thread."""
        try:
            self._channels.record_heard(call.conversation_id, heard)
        except Exception as exc:
            log.error(
                "voice heard text not stored",
                extra={
                    "visitor_id": str(call.visitor_id),
                    "conversation_id": str(call.conversation_id),
                    "call_sid": call_sid,
                    "error": type(exc).__name__,
                },
            )

    def over_time(self, call: VoiceCall) -> bool:
        """The call has lasted `VOICE_MAX_CALL_SECONDS` (used where nothing else holds the call
        open: gather mode checks it on every turn)."""
        return self._now() - call.started_at >= self._max_call

    def answer(self, call: VoiceCall, text: str, call_sid: str = "") -> str:
        """Run one turn and return what to say. Never raises: a failed turn is a spoken apology.
        Blocking (LLM, database): call it from a thread, not from the event loop."""
        fields = {
            "visitor_id": str(call.visitor_id),
            "conversation_id": str(call.conversation_id),
            "call_sid": call_sid,
        }
        try:
            result = self._chat.handle_turn(
                call.conversation_id, text, call.visitor_id, channel="voice"
            )
            return format_for_speech(result.reply, self._link_phrase) or NO_ANSWER
        except Exception as exc:
            # Only the exception type: its message and traceback can carry the caller's words
            # (SQLAlchemy errors print the statement parameters).
            log.error("voice turn failed", extra={**fields, "error": type(exc).__name__})
            return APOLOGY
        finally:
            self._flush()
