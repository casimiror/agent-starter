"""Outbound WhatsApp messages through Twilio's REST API.

A client of an external API, so it sits beside the services, not inside one: `WhatsAppService`
only knows the `send` method and gets this class (or a fake) from `app/api/deps.py`.
"""

import logging

import requests
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

log = logging.getLogger("app.whatsapp")


class WhatsAppSender:
    def __init__(self, client: Client) -> None:
        self._client = client

    def send(self, to: str, from_: str, body: str) -> str | None:
        """Send one message; returns Twilio's message SID, or None when it could not be sent.

        Never raises: it runs in a background task, where an exception would only be lost. Logs
        the Twilio error code and HTTP status, never `str(exc)` (it can hold the phone number)."""
        try:
            message = self._client.messages.create(to=to, from_=from_, body=body)
        except TwilioRestException as exc:
            log.error("whatsapp send failed", extra={"twilio_code": exc.code, "status": exc.status})
            return None
        except requests.RequestException as exc:
            log.error("whatsapp send failed", extra={"error": type(exc).__name__})
            return None
        return message.sid
