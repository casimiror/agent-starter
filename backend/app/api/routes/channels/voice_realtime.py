"""Voice, `VOICE_MODE=realtime`: Twilio Media Streams connects here with the call's audio and a
speech-to-speech model answers it. WebSocket only; the call itself is `RealtimeSession`
(services/voice_realtime.py).

The app must run on a host that keeps WebSockets open for the whole call (a container or VM), not
Vercel functions.
"""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, status
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_realtime_connector, get_realtime_voice_service
from app.api.twilio_security import handshake_valid
from app.clients.realtime import RealtimeConnector
from app.core.config import Settings, get_settings
from app.services import voice_twiml
from app.services.realtime_voice_service import RealtimeVoiceService
from app.services.voice_realtime import RealtimeSession

log = logging.getLogger("app.voice")
router = APIRouter(tags=["voice"])


@router.websocket("/channels/voice/stream")
async def stream_socket(
    websocket: WebSocket,
    service: Annotated[RealtimeVoiceService, Depends(get_realtime_voice_service)],
    connector: Annotated[RealtimeConnector, Depends(get_realtime_connector)],
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
        service, connector, receive, websocket.send_json, settings.voice_max_call_seconds
    )
    try:
        await session.run()
    finally:
        try:
            await websocket.close()
        except (RuntimeError, OSError):  # already closed by the peer
            pass
