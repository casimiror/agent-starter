"""Twilio WhatsApp webhook. HTTP only: size cap, signature, parsing, dedupe, scheduling.

Twilio gives a webhook about 15 seconds; a turn can take longer. So the route answers at once with
an empty TwiML document and the reply is sent later by `WhatsAppService` through the REST API,
from a background task.
"""

import logging
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from twilio.request_validator import RequestValidator

from app.api.deps import get_whatsapp_dedupe, get_whatsapp_service
from app.core.config import Settings, get_settings
from app.core.dedupe import RecentIds
from app.services.whatsapp_service import WhatsAppService

log = logging.getLogger("app.whatsapp")
router = APIRouter(tags=["whatsapp"])

WEBHOOK_PATH = "/api/channels/whatsapp/webhook"
# Twilio's form is a few hundred bytes; this only stops a flood of junk before it is parsed.
MAX_BODY_BYTES = 64 * 1024
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


async def _read_body(request: Request) -> bytes:
    """The request body, refusing anything over MAX_BODY_BYTES with 413: by Content-Length when
    sent, and while streaming when it is not (chunked uploads, or a lying header)."""
    too_large = HTTPException(413, "Body too large")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise too_large
    return bytes(body)


@router.post("/channels/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    background: BackgroundTasks,
    service: Annotated[WhatsAppService, Depends(get_whatsapp_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    dedupe: Annotated[RecentIds, Depends(get_whatsapp_dedupe)],
) -> Response:
    body = await _read_body(request)
    params = dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))

    # Twilio signs the exact public URL plus the form fields. Built from PUBLIC_BASE_URL, never
    # from request.url: a proxy or tunnel rewrites the scheme and host we see.
    signature = request.headers.get("X-Twilio-Signature", "")
    url = settings.public_base_url.rstrip("/") + WEBHOOK_PATH
    if not RequestValidator(settings.twilio_auth_token).validate(url, params, signature):
        log.warning("whatsapp webhook with an invalid signature")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")

    sender, message_sid = params.get("From", ""), params.get("MessageSid", "")
    if not sender or not message_sid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing From or MessageSid")

    # Twilio retries a webhook it considers failed. Checked after the signature, so only genuine
    # calls can fill the table.
    if dedupe.seen_before(message_sid):
        log.info("whatsapp duplicate dropped", extra={"message_sid": message_sid})
        return _empty_twiml()

    num_media = int(params["NumMedia"]) if params.get("NumMedia", "").isdigit() else 0
    to, text = params.get("To", ""), params.get("Body", "")
    background.add_task(service.handle_message, sender, to, text, num_media, message_sid)
    return _empty_twiml()


def _empty_twiml() -> Response:
    return Response(EMPTY_TWIML, media_type="application/xml")
