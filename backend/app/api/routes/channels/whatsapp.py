"""Twilio WhatsApp webhook. HTTP only: size cap, signature, parsing, dedupe, scheduling.

Twilio gives a webhook about 15 seconds; a turn can take longer. So the route answers at once with
an empty TwiML document and the reply is sent later by `WhatsAppService` through the REST API,
from a background task.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status

from app.api.deps import get_whatsapp_dedupe, get_whatsapp_service
from app.api.routes.channels.twilio_security import public_url, verified_form
from app.core.config import Settings, get_settings
from app.core.dedupe import RecentIds
from app.services.whatsapp_service import WhatsAppService

log = logging.getLogger("app.whatsapp")
router = APIRouter(tags=["whatsapp"])

WEBHOOK_PATH = "/api/channels/whatsapp/webhook"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@router.post("/channels/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    background: BackgroundTasks,
    service: Annotated[WhatsAppService, Depends(get_whatsapp_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    dedupe: Annotated[RecentIds, Depends(get_whatsapp_dedupe)],
) -> Response:
    # 413 for a big body, 403 for a bad signature (checked against PUBLIC_BASE_URL).
    params = await verified_form(request, settings, public_url(settings, WEBHOOK_PATH), "whatsapp")

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
