import logging
from collections.abc import Callable
from contextlib import ExitStack
from typing import Protocol

from app.core import observability
from app.core.rate_limit import hit_sender
from app.services.channels.conversations import ChannelConversations
from app.services.channels.whatsapp.format import MAX_MESSAGE_CHARS, format_for_whatsapp
from app.services.chat_service import ChatService

log = logging.getLogger("app.whatsapp")

TEXT_ONLY = "I can only read text messages for now. Could you write your question?"
SLOW_DOWN = "You're writing quite fast. Please wait a minute and try again."
APOLOGY = "Sorry, something went wrong on my side. Please try again in a moment."


class MessageSender(Protocol):
    def send(self, to: str, from_: str, body: str) -> str | None: ...


class WhatsAppService:
    """One inbound WhatsApp message handled end to end: limit, turn, reply. Runs as a background
    task after the webhook already answered Twilio, so every reply goes out through the REST API.
    No HTTP and no Twilio request code here."""

    def __init__(
        self,
        channels: ChannelConversations,
        chat: ChatService,
        sender: MessageSender,
        rate_limit: str,
        hit: Callable[[str, str, str], bool] = hit_sender,
        flush: Callable[[], None] = observability.flush,
    ) -> None:
        self._channels = channels
        self._chat = chat
        self._sender = sender
        self._rate_limit = rate_limit
        self._hit = hit
        self._flush = flush

    def handle_message(
        self, sender: str, to: str, body: str, num_media: int, message_sid: str
    ) -> None:
        """`sender` is Twilio's `From` and `to` our number: both are personal data, used only to
        address the reply. Logs carry the anonymous visitor id and the message SID. Never raises."""
        visitor_id = self._channels.visitor_id(sender)
        fields = {"visitor_id": str(visitor_id), "message_sid": message_sid}
        try:
            if not self._hit(self._rate_limit, "whatsapp", str(visitor_id)):
                log.warning("whatsapp sender over the limit", extra=fields)
                self._sender.send(to=sender, from_=to, body=SLOW_DOWN)
                return
            text = body.strip()
            if num_media > 0 or not text:
                self._sender.send(to=sender, from_=to, body=TEXT_ONLY)
                return
            self._answer(visitor_id, sender, to, text, fields)
        except Exception as exc:
            # Background task: an escaped exception would only be lost. The sender never raises,
            # so this is a bug elsewhere (limiter storage, ...); the user still gets an answer.
            log.error("whatsapp message failed", extra={**fields, "error": type(exc).__name__})
            self._sender.send(to=sender, from_=to, body=APOLOGY)
        finally:
            self._flush()

    def _answer(self, visitor_id, sender: str, to: str, text: str, fields: dict) -> None:
        # Hand over hand: the turn lock covers resolve + turn only. Before releasing it we take
        # the send lock, so the next message's turn can run while this reply goes out (a slow
        # Twilio doesn't stall the sender) and replies still leave in order.
        with ExitStack() as sending:
            with self._channels.lock(visitor_id):
                try:
                    conversation_id = self._channels.resolve(visitor_id, "whatsapp")
                    result = self._chat.handle_turn(
                        conversation_id, text, visitor_id, channel="whatsapp"
                    )
                except Exception as exc:
                    # Only the exception type: its message and traceback can carry the user's text
                    # (SQLAlchemy errors print the statement parameters).
                    log.error("whatsapp turn failed", extra={**fields, "error": type(exc).__name__})
                    parts = [APOLOGY]
                else:
                    parts = self._format(result.reply, fields)
                sending.enter_context(self._channels.send_lock(visitor_id))
            for part in parts:
                if self._sender.send(to=sender, from_=to, body=part) is None:
                    # The sender returns None on failure: the later parts would arrive without
                    # the earlier one, and each retry could wait out the timeout again.
                    log.warning("whatsapp reply cut short", extra=fields)
                    break

    @staticmethod
    def _format(reply: str, fields: dict) -> list[str]:
        """The reply as WhatsApp messages. The turn is already saved, so a formatting bug must not
        turn into an apology: fall back to the raw reply, cut to one message."""
        try:
            return format_for_whatsapp(reply)
        except Exception as exc:
            log.error("whatsapp formatting failed", extra={**fields, "error": type(exc).__name__})
            return [reply.replace("\x00", "")[:MAX_MESSAGE_CHARS]]
