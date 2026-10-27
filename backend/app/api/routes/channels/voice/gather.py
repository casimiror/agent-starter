"""Voice, `VOICE_MODE=gather`: Twilio listens with <Gather input="speech"> and posts the
transcript here; the TwiML we answer with speaks the reply and listens again.

The turn runs inside the webhook, so it must finish within Twilio's ~15 s timeout (a tool call or
a fallback model can exceed it): that is this mode's limit, and the price of needing nothing but
HTTP, which is why it also works on serverless hosts.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_voice_service
from app.api.routes.channels.twilio_security import public_url, verified_form
from app.api.routes.channels.voice.modes import only
from app.core.config import Settings, get_settings
from app.services.channels.voice import twiml as voice_twiml
from app.services.channels.voice.service import VoiceService

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"], dependencies=[Depends(only("gather"))])


def _twiml(document: str) -> Response:
    return Response(document, media_type="application/xml")


@router.post("/channels/voice/gather")
async def gather(
    request: Request,
    service: Annotated[VoiceService, Depends(get_voice_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    # Twilio signs the full URL, query string included. We emitted `?c=<id>[&r=1]` ourselves
    # (voice_twiml.gather_url), so the exact string it calls back is what we validate.
    query = request.url.query
    url = public_url(settings, voice_twiml.GATHER_PATH) + (f"?{query}" if query else "")
    params = await verified_form(request, settings, url, "voice")

    call_sid = params.get("CallSid", "")
    call = None
    try:
        conversation_id = UUID(request.query_params.get("c", ""))
        call = await run_in_threadpool(service.find_call, conversation_id)
    except ValueError:
        pass
    if call is None:
        # A signed request for a conversation that isn't a voice call of ours: never open a new
        # conversation for it, just end the call.
        log.warning("voice gather for an unknown conversation", extra={"call_sid": call_sid})
        return _twiml(voice_twiml.say_and_hang_up(settings, voice_twiml.SOMETHING_WRONG))
    if service.over_time(call):
        return _twiml(voice_twiml.say_and_hang_up(settings, voice_twiml.TIME_UP))

    speech = params.get("SpeechResult", "").strip()
    if not speech:
        # `r` counts the silences so far: the first one is re-prompted, the second hangs up.
        silences = (
            int(request.query_params["r"]) if request.query_params.get("r", "").isdigit() else 0
        )
        if silences >= 1:
            return _twiml(voice_twiml.say_and_hang_up(settings, voice_twiml.NO_INPUT_GOODBYE))
        return _twiml(
            voice_twiml.gather_say(settings, voice_twiml.DIDNT_CATCH, call.conversation_id, 1)
        )

    reply = await run_in_threadpool(service.answer, call, speech, call_sid)
    return _twiml(voice_twiml.gather_say(settings, reply, call.conversation_id))
