import logging
from collections.abc import Callable
from typing import Protocol

from app.core import observability
from app.core.rate_limit import hit_sender
from app.services.channel_conversations import ChannelConversations
from app.services.chat_service import ChatService
from app.services.whatsapp_format import format_for_whatsapp

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
        # Replies are sent inside the lock too, so two quick messages are answered in order.
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
                self._sender.send(to=sender, from_=to, body=APOLOGY)
                return
            for part in format_for_whatsapp(result.reply):
                self._sender.send(to=sender, from_=to, body=part)
