"""OpenAI Realtime API as a voice model provider, over a WebSocket.

All the OpenAI-specific knowledge lives here: the URL and auth, the `session.update` that turns a
connection into the agent, the client events that implement each neutral command and the
translation of server events into the neutral ones (base.py). Event and error names marked
UNVERIFIED come from the API reference as summarised, not from a live session: check them against
a real call before relying on them.
"""

import json
import logging
from typing import Any, ClassVar

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.clients.voice_models.base import (
    MULAW_8K,
    AssistantTranscriptDelta,
    AssistantTranscriptDone,
    AudioChunk,
    AudioFormat,
    CallerSpeaking,
    ModelError,
    ModelEvent,
    ResponseDone,
    ResponseStarted,
    SessionReady,
    ToolCall,
    UserTranscript,
    UserTranscriptFailed,
    UserTurnEnded,
    VoiceModelConfig,
    VoiceModelConnection,
    VoiceModelError,
    VoiceSessionSpec,
)

log = logging.getLogger("app.voice")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
# Audio deltas are a few KB; the default 1 MiB limit is already generous, this leaves headroom.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 10.0

# The wire name of each audio format OpenAI accepts here.
WIRE_AUDIO_FORMATS = {MULAW_8K: {"type": "audio/pcmu"}}

# Errors that mean the model session can't go on. Matched on `type`/`code` of the `error` event;
# anything else is logged and the call goes on (a failed cancel or truncate is routine). Names are
# from the API reference as summarised; an error before `session.updated` is always fatal (the
# bridge decides that one: it knows whether the session was ready).
FATAL_ERROR_TYPES = {"server_error", "authentication_error", "insufficient_quota"}
FATAL_ERROR_CODES = {"invalid_api_key", "insufficient_quota", "session_expired", "model_not_found"}
# The error code of a `response.create` sent while another response is still active. UNVERIFIED
# name: if the API words it differently the call still works (the error is logged and the flags
# are reset); only the automatic retry in the bridge does not happen.
ACTIVE_RESPONSE_CODES = {"conversation_already_has_active_response"}


def say_instructions(text: str) -> str:
    return (
        "Say exactly the following to the caller, word for word, and nothing else. "
        f"Do not add, explain or call tools: {text}"
    )


def tool_payload(spec: VoiceSessionSpec) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in spec.tools
    ]


def translate(event: dict[str, Any]) -> ModelEvent | None:
    """One OpenAI server event as a neutral one, or None when the bridge has no use for it."""
    kind = event.get("type")
    if kind == "response.output_audio.delta":
        return AudioChunk(
            str(event.get("response_id") or ""),
            str(event.get("item_id") or ""),
            str(event.get("delta") or ""),
        )
    if kind == "response.output_audio_transcript.delta":
        return AssistantTranscriptDelta(
            str(event.get("response_id") or ""), str(event.get("delta") or "")
        )
    if kind == "response.output_audio_transcript.done":
        return AssistantTranscriptDone(
            str(event.get("response_id") or ""), str(event.get("transcript") or "")
        )
    if kind == "input_audio_buffer.speech_started":
        return CallerSpeaking()
    if kind in ("input_audio_buffer.committed", "input_audio_buffer.speech_stopped"):
        # UNVERIFIED names: either one means the caller's turn ended (both carry `item_id`; the
        # bridge acts on the first to arrive, so a missing one can't leave the call silent).
        return UserTurnEnded(str(event.get("item_id") or ""))
    if kind == "conversation.item.input_audio_transcription.completed":
        return UserTranscript(
            str(event.get("item_id") or ""), str(event.get("transcript") or "").strip()
        )
    if kind == "conversation.item.input_audio_transcription.failed":  # UNVERIFIED name
        return UserTranscriptFailed(str(event.get("item_id") or ""))
    if kind == "response.function_call_arguments.done":
        return _tool_call(event.get("response_id"), event)
    if kind == "response.created":
        response_id = str((event.get("response") or {}).get("id") or "")
        return ResponseStarted(response_id) if response_id else None
    if kind == "response.done":
        return _response_done(event.get("response") or {})
    if kind == "response.cancelled":
        # A cancellation is reported by this event or by response.done with status "cancelled";
        # whichever comes first closes the response, the bridge ignores the other.
        response_id = event.get("response_id") or (event.get("response") or {}).get("id")
        return ResponseDone(str(response_id or ""), "cancelled")
    if kind == "session.updated":
        return SessionReady()
    if kind == "error":
        return _model_error(event.get("error") or {})
    return None


def _tool_call(response_id: Any, data: dict[str, Any]) -> ToolCall | None:
    call_id = str(data.get("call_id") or "")
    if not call_id or not response_id:
        return None
    return ToolCall(
        str(response_id), call_id, str(data.get("name") or ""), str(data.get("arguments") or "")
    )


def _response_done(data: dict[str, Any]) -> ResponseDone:
    response_id = str(data.get("id") or "")
    calls: list[ToolCall] = []
    item_id = ""
    for item in data.get("output") or []:
        if item.get("type") == "function_call":
            if call := _tool_call(response_id, item):
                calls.append(call)
        elif item.get("type") == "message" and not item_id:
            item_id = str(item.get("id") or "")
    return ResponseDone(response_id, str(data.get("status") or "completed"), item_id, tuple(calls))


def _model_error(error: dict[str, Any]) -> ModelError:
    kind, code = str(error.get("type") or ""), str(error.get("code") or "")
    return ModelError(
        kind=kind,
        code=code,
        fatal=kind in FATAL_ERROR_TYPES or code in FATAL_ERROR_CODES,
        active_response=code in ACTIVE_RESPONSE_CODES,
    )


class _OpenAIConnection:
    def __init__(self, socket: Any, config: VoiceModelConfig) -> None:
        self._socket = socket
        self._config = config

    async def _send(self, event: dict[str, Any]) -> None:
        await self._socket.send(json.dumps(event))

    async def configure(self, spec: VoiceSessionSpec) -> None:
        await self._send(session_update(self._config, spec))

    async def append_audio(self, audio: str) -> None:
        await self._send({"type": "input_audio_buffer.append", "audio": audio})

    async def respond(self) -> None:
        await self._send({"type": "response.create"})

    async def say(self, text: str) -> None:
        await self._send(
            {
                "type": "response.create",
                "response": {"instructions": say_instructions(text), "tool_choice": "none"},
            }
        )

    async def cancel(self) -> None:
        await self._send({"type": "response.cancel"})

    async def truncate(self, item_id: str, audio_end_ms: int) -> None:
        await self._send(
            {
                "type": "conversation.item.truncate",
                "item_id": item_id,
                "content_index": 0,
                "audio_end_ms": audio_end_ms,
            }
        )

    async def tool_result(self, call_id: str, output: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": output},
            }
        )

    async def receive(self) -> ModelEvent | None:
        while True:
            try:
                raw = await self._socket.recv()
            except ConnectionClosed:
                return None
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and (neutral := translate(event)) is not None:
                return neutral

    async def close(self) -> None:
        await self._socket.close()


def session_update(config: VoiceModelConfig, spec: VoiceSessionSpec) -> dict[str, Any]:
    """The `session.update` event that turns a fresh connection into the agent: the audio format
    both ways, server-side voice detection, the agent's prompt and tools. The model is chosen in
    the connection URL. `config.language` is not sent: transcription and speech follow the
    caller's language."""
    audio_format = WIRE_AUDIO_FORMATS[MULAW_8K]
    detection = config.turn_detection
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": dict(audio_format),
                    # The server only detects turns. We create every response ourselves, after
                    # the input guardrails ran on the transcript (the bridge); interrupt_response
                    # makes the server cancel a reply on barge-in (we still send `clear` and
                    # `truncate`). UNVERIFIED against a live session: the two field names, from
                    # the API reference as summarised.
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": detection.create_response,
                        "interrupt_response": detection.interrupt_response,
                    },
                    "transcription": {"model": config.transcription_model},
                },
                "output": {"format": dict(audio_format), "voice": config.voice},
            },
            "instructions": spec.instructions,
            "tools": tool_payload(spec),
            "tool_choice": "auto",
        },
    }


class OpenAIRealtimeProvider:
    """Opens `wss://api.openai.com/v1/realtime?model=...` with the API key as a bearer token (the
    GA interface: no `OpenAI-Beta` header). No `OpenAI-Safety-Identifier` is sent: the only id we
    hold for a caller is an anonymous visitor id, and the caller's number never leaves the app."""

    name: ClassVar[str] = "openai"
    # What `VoiceModelBuilder.build()` checks, and the setting that holds the key.
    required: ClassVar[tuple[str, ...]] = ("model", "api_key", "voice", "transcription_model")
    api_key_setting: ClassVar[str] = "openai_api_key"
    api_key_env: ClassVar[str] = "OPENAI_API_KEY"
    # UNVERIFIED: the realtime voices as listed in the API reference as summarised (the GA
    # `marin` and `cedar` are realtime-only). Check the list against the current docs, and add a
    # voice here before using one OpenAI releases later: `build()` rejects names not in it.
    voices: ClassVar[frozenset[str] | None] = frozenset(
        {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"}
    )
    audio_format: AudioFormat = MULAW_8K  # Twilio's mu-law 8 kHz: OpenAI takes it as is

    def __init__(self, config: VoiceModelConfig) -> None:
        self._config = config
        self.model = config.model

    async def connect(self) -> VoiceModelConnection:
        url = self._config.endpoint or OPENAI_REALTIME_URL
        try:
            socket = await connect(
                f"{url}?model={self._config.model}",
                additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
                max_size=MAX_MESSAGE_BYTES,
                open_timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            # The exception type only: it must never be able to echo a header.
            log.error(
                "realtime connection failed",
                extra={"provider": self.name, "error": type(exc).__name__},
            )
            raise VoiceModelError(
                "could not connect to the realtime API", kind=type(exc).__name__
            ) from None
        return _OpenAIConnection(socket, self._config)
