"""The connection to a speech-to-speech model (OpenAI Realtime API), over a WebSocket.

`RealtimeSession` only knows the two small Protocols below, so tests inject a fake and a
future provider (Gemini Live) is another connector with the same shape. Events are plain dicts: the
JSON the provider sends and expects.
"""

import json
import logging
from typing import Any, Protocol

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

log = logging.getLogger("app.voice")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
# Audio deltas are a few KB; the default 1 MiB limit is already generous, this leaves headroom.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 10.0


class RealtimeError(Exception):
    """The connection could not be opened. The message never carries credentials."""


class RealtimeConnection(Protocol):
    async def send(self, event: dict[str, Any]) -> None:
        """Send one client event. Raises when the connection is closed."""

    async def receive(self) -> dict[str, Any] | None:
        """The next server event, or None once the connection is closed."""

    async def close(self) -> None: ...


class RealtimeConnector(Protocol):
    async def connect(self) -> RealtimeConnection:
        """Open a connection. Raises `RealtimeError`."""


class _WebsocketConnection:
    def __init__(self, socket: Any) -> None:
        self._socket = socket

    async def send(self, event: dict[str, Any]) -> None:
        await self._socket.send(json.dumps(event))

    async def receive(self) -> dict[str, Any] | None:
        while True:
            try:
                raw = await self._socket.recv()
            except ConnectionClosed:
                return None
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict):
                return event

    async def close(self) -> None:
        await self._socket.close()


class OpenAIRealtimeConnector:
    """Opens `wss://api.openai.com/v1/realtime?model=...` with the API key as a bearer token (the
    GA interface: no `OpenAI-Beta` header). No `OpenAI-Safety-Identifier` is sent: the only id we
    hold for a caller is an anonymous visitor id, and the caller's number never leaves the app."""

    def __init__(self, api_key: str, model: str, url: str = OPENAI_REALTIME_URL) -> None:
        self._api_key = api_key
        self._model = model
        self._url = url

    async def connect(self) -> RealtimeConnection:
        try:
            socket = await connect(
                f"{self._url}?model={self._model}",
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                max_size=MAX_MESSAGE_BYTES,
                open_timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            # The exception type only: it must never be able to echo a header.
            log.error("realtime connection failed", extra={"error": type(exc).__name__})
            raise RealtimeError("could not connect to the realtime API") from None
        return _WebsocketConnection(socket)
