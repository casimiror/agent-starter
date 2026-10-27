"""Twilio voice channel: "a call comes in". HTTP only: size cap, signature, caller limit, TwiML.

`/incoming` is common to every `VOICE_MODE`; the mode picks the TwiML it answers with and owns the
rest of the call (`relay.py`: WebSocket, `gather.py`: webhook per turn, `realtime.py`: Media
Streams WebSocket). `__init__.py` assembles them into the voice router.
"""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_voice_service
from app.api.routes.channels.twilio_security import public_url, verified_form
from app.core.config import Settings, get_settings
from app.services.channels.voice import twiml as voice_twiml
from app.services.channels.voice.service import VoiceService

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"])

# A real caller is E.164: `+` and at least 8 digits. Anything else (empty, "anonymous",
# "restricted", "unavailable", "unknown", or Twilio's placeholder numbers such as +266696687,
# +7378742833, +86282452253) stands for every caller who hides their number: hashing it would give
# them all one visitor (and one rate limit).
_REAL_NUMBER = re.compile(r"\+\d{8,}")
# Numbers that look real but are Twilio's placeholders for a hidden caller.
_PLACEHOLDER_NUMBERS = {"+266696687", "+7378742833", "+86282452253"}


def _is_hidden(caller: str) -> bool:
    return not _REAL_NUMBER.fullmatch(caller) or caller in _PLACEHOLDER_NUMBERS


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
    caller = call_sid if _is_hidden(caller.strip()) else caller
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
