"""Voice, `VOICE_MODE=relay` (Twilio ConversationRelay): Twilio does speech-to-text and
text-to-speech and talks to this WebSocket in JSON text. WebSocket and HTTP only; the message
handling is `RelaySession` (services/channels/voice/relay.py).

The app must run on a host that keeps WebSockets open (a container or VM), not Vercel functions.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, WebSocket, status
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_relay_clock, get_voice_service
from app.api.routes.channels.twilio_security import handshake_valid, public_url, verified_form
from app.api.routes.channels.voice.modes import only
from app.core.config import Settings, get_settings
from app.services.channels.voice import twiml as voice_twiml
from app.services.channels.voice.relay import RelaySession
from app.services.channels.voice.service import VoiceService

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"])


@router.websocket("/channels/voice/relay/ws")
async def relay_socket(
    websocket: WebSocket,
    service: Annotated[VoiceService, Depends(get_voice_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Callable[[], float], Depends(get_relay_clock)],
) -> None:
    # The handshake has no body: Twilio signs the wss URL alone. Rejected before accepting, so
    # an unsigned client never gets a socket.
    signature = websocket.headers.get("x-twilio-signature", "")
    if settings.voice_mode != "relay" or not handshake_valid(
        settings, voice_twiml.relay_ws_url(settings), signature
    ):
        log.warning("voice relay handshake rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    session = RelaySession(
        service, settings.voice_max_call_seconds, clock, settings.voice_max_pending_turns
    )
    turns: set[asyncio.Task] = set()

    async def respond(message: dict) -> None:
        try:
            for outgoing in await session.handle(message):
                await websocket.send_json(outgoing)
        except (
            Exception
        ) as exc:  # peer gone mid-turn, or a bug: the call must not take the app down
            log.error("voice relay message failed", extra={"error": type(exc).__name__})

    try:
        while True:
            try:
                event = await asyncio.wait_for(websocket.receive(), session.remaining())
            except TimeoutError:
                if session.ended:  # we asked Twilio to end and it has not closed yet
                    break
                log.info("voice call reached its time limit", extra={"call_sid": session.call_sid})
                for outgoing in session.end():
                    await websocket.send_json(outgoing)
                continue
            if event["type"] == "websocket.disconnect":
                break
            try:
                message = json.loads(event.get("text") or "")
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "prompt":
                # A turn takes seconds: run it aside so interrupts and errors are still read.
                # The session's lock keeps overlapping prompts one at a time, in order.
                task = asyncio.create_task(respond(message))
                turns.add(task)
                task.add_done_callback(turns.discard)
            else:
                await respond(message)  # setup must finish before the first prompt is read
    except WebSocketDisconnect:
        pass
    finally:
        for task in turns:
            task.cancel()
        # Wait for them to finish cancelling so none outlives the socket (or logs "never
        # retrieved"); their errors were already handled in `respond`.
        await asyncio.gather(*turns, return_exceptions=True)
        try:
            await websocket.close()
        except (RuntimeError, OSError):  # already closed by the peer
            pass


@router.post("/channels/voice/relay/action", dependencies=[Depends(only("relay"))])
async def relay_action(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Response:
    """Twilio calls this when the ConversationRelay session ends (we sent `end`, the caller hung
    up, or it failed). Nothing follows the session, so the answer is a hang-up."""
    params = await verified_form(
        request, settings, public_url(settings, voice_twiml.RELAY_ACTION_PATH), "voice"
    )
    log.info(
        "voice relay session ended",
        extra={
            "call_sid": params.get("CallSid", ""),
            "session_status": params.get("SessionStatus", ""),
            "session_duration": params.get("SessionDuration", ""),
            "error_code": params.get("ErrorCode", ""),
        },
    )
    return Response(voice_twiml.hang_up(), media_type="application/xml")
