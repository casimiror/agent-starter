"""Twilio voice channel: "a call comes in". HTTP only: size cap, signature, caller limit, TwiML.

`/incoming` is common to every `VOICE_MODE`; the mode picks the TwiML it answers with and owns the
rest of the call (`voice_relay.py`: WebSocket, `voice_gather.py`: webhook per turn).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_voice_service
from app.api.routes.channels import voice_gather, voice_relay
from app.api.twilio_security import public_url, verified_form
from app.core.config import Settings, get_settings
from app.services import voice_twiml
from app.services.voice_service import VoiceService

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"])
router.include_router(voice_relay.router)
router.include_router(voice_gather.router)

# What Twilio sends as `From` when the caller hides their number: shared by every such caller, so
# hashing it would give them all one visitor (and one rate limit).
_HIDDEN_CALLERS = {"", "anonymous", "+266696687"}


def twiml_response(document: str) -> Response:
    return Response(document, media_type="application/xml")


@router.post("/channels/voice/incoming")
async def incoming(
    request: Request,
    service: Annotated[VoiceService, Depends(get_voice_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    params = await verified_form(
        request, settings, public_url(settings, voice_twiml.INCOMING_PATH), "voice"
    )
    call_sid = params.get("CallSid", "")
    if not call_sid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing CallSid")

    # The number is personal data: it only goes into the keyed hash. A hidden number falls back to
    # the call's own SID, so such callers are not lumped together.
    caller = params.get("From", "")
    caller = call_sid if caller.lower() in _HIDDEN_CALLERS else caller
    try:
        call = await run_in_threadpool(service.start_call, caller, call_sid)
    except Exception as exc:
        # Database or limiter storage down: tell the caller instead of Twilio's generic error.
        log.error(
            "voice call not started", extra={"call_sid": call_sid, "error": type(exc).__name__}
        )
        return twiml_response(voice_twiml.say_and_hang_up(settings, voice_twiml.SOMETHING_WRONG))
    if call is None:
        return twiml_response(voice_twiml.say_and_hang_up(settings, voice_twiml.TOO_MANY_CALLS))
    build = voice_twiml.INCOMING[settings.voice_mode]
    return twiml_response(build(settings, call.visitor_id, call.conversation_id))
