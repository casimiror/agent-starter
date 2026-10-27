import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.services.channels.voice.service import VoiceCall, VoiceService

log = logging.getLogger("app.voice")

END = {"type": "end"}
# After we send `end`, Twilio closes the socket itself; this is how long we wait before doing it.
GRACE_SECONDS = 5.0


class RelaySession:
    """One ConversationRelay WebSocket: Twilio's JSON messages in, our JSON messages out. No
    socket code here (the route owns it), so it is tested with plain dicts.

    Messages: `setup` binds the session to the conversation created when the call came in;
    `prompt` is a final transcript and runs one turn; `interrupt` trims the stored reply to what
    the caller heard; `dtmf` and `error` are only logged. Twilio's `setup.from` (the caller's
    number) is never read."""

    def __init__(
        self,
        voice: VoiceService,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_pending: int = 2,
    ) -> None:
        self._voice = voice
        self._max_pending = max_pending
        self._pending = 0  # prompts running or waiting for the turn lock
        self._max_seconds = max_seconds
        self._clock = clock
        self._started = clock()
        # One turn at a time: a caller who speaks again while a reply is being produced queues
        # behind it, so two turns never write to the same conversation concurrently.
        self._turn = asyncio.Lock()
        self.call: VoiceCall | None = None
        self.call_sid = ""
        self.ended = False
        # A reply was sent and no interrupt has trimmed it yet (the greeting is not a reply).
        self._unheard_reply = False
        self._setup_seen = False

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
            log.info(
                "voice reply interrupted",
                extra={**self._fields(), "after_ms": message.get("durationUntilInterruptMs")},
            )
            await self._interrupt(message)
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
        if self._setup_seen:
            # A second setup could rebind the session to another conversation: only the first
            # counts. Nothing from the message is logged.
            log.warning("voice setup ignored, already set up", extra=self._fields())
            return []
        self._setup_seen = True
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

    async def _interrupt(self, message: dict[str, Any]) -> None:
        """Keep in the history only what the caller heard of the last reply
        (`utteranceUntilInterrupt`). Acts once per reply sent, and not while a turn is running:
        then the last stored assistant message may already be a newer reply (Twilio sends the
        interrupt before the next prompt, so this is the rare case)."""
        if self.call is None or not self._unheard_reply or self._turn.locked():
            return
        self._unheard_reply = False
        # "…" when nothing was heard: an empty assistant message would break some providers.
        heard = str(message.get("utteranceUntilInterrupt") or "").strip() or "…"
        await asyncio.to_thread(self._voice.record_heard, self.call, heard, self.call_sid)

    async def _prompt(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        # With partial prompts a transcript may arrive in pieces; only the final one is a turn.
        if message.get("last", True) is not True:
            return []
        text = str(message.get("voicePrompt") or "").strip()
        if not text or self.call is None:
            return []
        if self._pending >= self._max_pending:
            # Never the text. Each queued prompt is an LLM turn we'd pay for and the caller
            # could not have waited for.
            log.warning("voice prompt dropped, too many pending", extra=self._fields())
            return []
        self._pending += 1
        try:
            async with self._turn:
                if self.ended:
                    return []
                if self.expired:
                    return self.end()
                reply = await asyncio.to_thread(self._voice.answer, self.call, text, self.call_sid)
                self._unheard_reply = True  # a later interrupt may cut this reply short
        finally:
            self._pending -= 1
        return [{"type": "text", "token": reply, "last": True}]
