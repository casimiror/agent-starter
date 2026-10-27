import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.services.voice_service import VoiceCall, VoiceService

log = logging.getLogger("app.voice")

END = {"type": "end"}
# After we send `end`, Twilio closes the socket itself; this is how long we wait before doing it.
GRACE_SECONDS = 5.0


class RelaySession:
    """One ConversationRelay WebSocket: Twilio's JSON messages in, our JSON messages out. No
    socket code here (the route owns it), so it is tested with plain dicts.

    Messages: `setup` binds the session to the conversation created when the call came in;
    `prompt` is a final transcript and runs one turn; `interrupt`, `dtmf` and `error` are only
    logged. Twilio's `setup.from` (the caller's number) is never read."""

    def __init__(
        self,
        voice: VoiceService,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._voice = voice
        self._max_seconds = max_seconds
        self._clock = clock
        self._started = clock()
        # One turn at a time: a caller who speaks again while a reply is being produced queues
        # behind it, so two turns never write to the same conversation concurrently.
        self._turn = asyncio.Lock()
        self.call: VoiceCall | None = None
        self.call_sid = ""
        self.ended = False

    @property
    def expired(self) -> bool:
        return self._clock() - self._started >= self._max_seconds

    def remaining(self) -> float:
        """Seconds the route may wait for the next message before it must act."""
        if self.ended:
            return GRACE_SECONDS
        return max(0.0, self._max_seconds - (self._clock() - self._started))

    def end(self) -> list[dict[str, Any]]:
        """Ask Twilio to end the session (it then calls the `action` URL)."""
        self.ended = True
        return [dict(END)]

    async def handle(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """The messages to send back for one received message."""
        if self.ended:
            return []
        if self.expired:
            log.info("voice call reached its time limit", extra=self._fields())
            return self.end()
        kind = message.get("type")
        if kind == "setup":
            return await self._setup(message)
        if kind == "prompt":
            return await self._prompt(message)
        if kind == "interrupt":
            # The stored assistant message keeps the whole reply: it is not trimmed to what the
            # caller heard (`utteranceUntilInterrupt`), so history may be longer than the call.
            log.info(
                "voice reply interrupted",
                extra={**self._fields(), "after_ms": message.get("durationUntilInterruptMs")},
            )
        elif kind == "dtmf":
            # Never the digit itself: keypad input can be an account or card number.
            log.info("voice dtmf received", extra=self._fields())
        elif kind == "error":
            log.warning(
                "voice relay error",
                extra={**self._fields(), "description": str(message.get("description"))[:200]},
            )
        return []

    def _fields(self) -> dict[str, str]:
        fields = {"call_sid": self.call_sid}
        if self.call:
            fields["visitor_id"] = str(self.call.visitor_id)
            fields["conversation_id"] = str(self.call.conversation_id)
        return fields

    async def _setup(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        self.call_sid = str(message.get("callSid") or "")
        parameters = message.get("customParameters") or {}
        try:
            conversation_id = UUID(str(parameters.get("conversation_id")))
        except ValueError:
            log.warning("voice setup without a conversation id", extra=self._fields())
            return self.end()
        # The visitor comes from the stored conversation, not from the parameter, as in
        # ChatService: one conversation never splits across visitors.
        self.call = await asyncio.to_thread(self._voice.find_call, conversation_id)
        if self.call is None:
            log.warning("voice setup for an unknown conversation", extra=self._fields())
            return self.end()
        log.info("voice relay connected", extra=self._fields())
        return []

    async def _prompt(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        # With partial prompts a transcript may arrive in pieces; only the final one is a turn.
        if message.get("last", True) is not True:
            return []
        text = str(message.get("voicePrompt") or "").strip()
        if not text or self.call is None:
            return []
        async with self._turn:
            if self.ended:
                return []
            if self.expired:
                return self.end()
            reply = await asyncio.to_thread(self._voice.answer, self.call, text, self.call_sid)
        return [{"type": "text", "token": reply, "last": True}]
