"""Voice, `VOICE_MODE=realtime`: Twilio Media Streams connects here with the call's audio and a
speech-to-speech model answers it. WebSocket only; the call itself is `RealtimeSession`
(services/channels/voice/realtime/session.py).

The app must run on a host that keeps WebSockets open for the whole call (a container or VM), not
Vercel functions.
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, status
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_realtime_voice_service, get_voice_models
from app.api.routes.channels.twilio_security import handshake_valid
from app.clients.voice_models.base import VoiceModelProvider
from app.core.config import Settings, get_settings
from app.services.channels.voice import twiml as voice_twiml
from app.services.channels.voice.realtime.service import RealtimeVoiceService
from app.services.channels.voice.realtime.session import RealtimeSession

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"])


@router.websocket("/channels/voice/stream")
async def stream_socket(
    websocket: WebSocket,
    service: Annotated[RealtimeVoiceService, Depends(get_realtime_voice_service)],
    voice_models: Annotated[list[VoiceModelProvider], Depends(get_voice_models)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    # The handshake has no body: Twilio signs the wss URL alone. Rejected before accepting, so
    # an unsigned client never gets a socket.
    signature = websocket.headers.get("x-twilio-signature", "")
    if settings.voice_mode != "realtime" or not handshake_valid(
        settings, voice_twiml.stream_url(settings), signature
    ):
        log.warning("voice stream handshake rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    async def receive() -> dict[str, Any] | None:
        while True:
            try:
                event = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):  # RuntimeError: receive after close
                return None
            if event["type"] == "websocket.disconnect":
                return None
            try:
                message = json.loads(event.get("text") or "")
            except ValueError:  # binary or not JSON: skip it
                continue
            if isinstance(message, dict):
                return message

    session = RealtimeSession(
        service,
        voice_models,
        receive,
        websocket.send_json,
        settings.voice_max_call_seconds,
        settings.voice_realtime_transcript_wait_ms / 1000,
    )
    try:
        await session.run()
    finally:
        try:
            await websocket.close()
        except (RuntimeError, OSError):  # already closed by the peer
            pass
