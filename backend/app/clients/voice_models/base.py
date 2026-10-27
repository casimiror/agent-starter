"""The neutral vocabulary between a realtime (speech-to-speech) voice model and the call bridge.

`RealtimeSession` (services/channels/voice/realtime/session.py) speaks only this: the events a model
tells us (dataclasses below) and the commands we give it (`VoiceModelConnection`). Each provider
module in this package translates between that and its own wire protocol, so the bridge never
sees a provider's event names.

Audio travels as base64 text, the form Twilio Media Streams already uses, so a provider whose
`audio_format` is Twilio's (mu-law 8 kHz) is a passthrough.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class VoiceModelError(Exception):
    """The connection to the model could not be opened. The message never carries credentials;
    `kind` is the type name of the underlying error, for logs."""

    def __init__(self, message: str, kind: str = "") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class AudioFormat:
    """What audio a model takes and returns, in both directions."""

    encoding: str  # "mulaw", "pcm16"...
    sample_rate: int  # Hz


# Twilio Media Streams: mu-law, 8 kHz, mono, one byte per sample.
MULAW_8K = AudioFormat("mulaw", 8000)


# --- what the model tells us -------------------------------------------------------------------


@dataclass(frozen=True)
class SessionReady:
    """The model accepted `configure`; its audio can flow in the agreed format."""


@dataclass(frozen=True)
class AudioChunk:
    response_id: str
    item_id: str  # the reply's audio item, what `truncate` refers to ("" if unknown)
    audio: str  # base64


@dataclass(frozen=True)
class AssistantTranscriptDelta:
    response_id: str
    text: str


@dataclass(frozen=True)
class AssistantTranscriptDone:
    response_id: str
    text: str


@dataclass(frozen=True)
class CallerSpeaking:
    """The caller started talking (barge-in)."""


@dataclass(frozen=True)
class UserTurnEnded:
    """The caller's turn ended; its transcript is on its way."""

    item_id: str


@dataclass(frozen=True)
class UserTranscript:
    item_id: str
    text: str


@dataclass(frozen=True)
class UserTranscriptFailed:
    item_id: str


@dataclass(frozen=True)
class ToolCall:
    response_id: str
    call_id: str
    name: str
    arguments: str  # the JSON text the model wrote; never logged


@dataclass(frozen=True)
class ResponseStarted:
    response_id: str


@dataclass(frozen=True)
class ResponseDone:
    response_id: str
    status: str  # "completed", "cancelled"...
    item_id: str = ""  # the reply's audio item, when the model reports it only here
    tool_calls: tuple[ToolCall, ...] = ()  # calls reported only in the final summary


@dataclass(frozen=True)
class ModelError:
    kind: str  # the provider's error type and code: logged, never the message
    code: str
    fatal: bool = False  # the model session cannot go on
    active_response: bool = False  # our `respond` was refused: a response is still being made


ModelEvent = (
    SessionReady
    | AudioChunk
    | AssistantTranscriptDelta
    | AssistantTranscriptDone
    | CallerSpeaking
    | UserTurnEnded
    | UserTranscript
    | UserTranscriptFailed
    | ToolCall
    | ResponseStarted
    | ResponseDone
    | ModelError
)


# --- what we ask of the model ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may call: name, description and the JSON schema of its arguments."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class VoiceSessionSpec:
    """The agent as the model sees it: the same prompt and tools the text agent has. How it
    sounds (voice, language, transcription, turn detection) is the provider's config."""

    instructions: str
    tools: tuple[ToolSpec, ...] = ()


@dataclass(frozen=True)
class TurnDetection:
    """Server-side detection of the caller's turns. The bridge creates every response itself
    (after the input guardrails ran), so `create_response` stays off."""

    create_response: bool = False
    interrupt_response: bool = True  # the model stops its own reply on barge-in


@dataclass(frozen=True)
class VoiceModelConfig:
    """What `VoiceModelBuilder` collects and a provider is built from."""

    model: str = ""
    api_key: str = field(default="", repr=False)
    voice: str = ""
    language: str = ""
    transcription_model: str = ""
    turn_detection: TurnDetection = field(default_factory=TurnDetection)
    endpoint: str = ""  # empty: the provider's own URL


class VoiceModelConnection(Protocol):
    """One open session with a model. Commands raise when the connection is closed."""

    async def configure(self, spec: VoiceSessionSpec) -> None:
        """Turn the fresh connection into this agent. The model answers with `SessionReady`."""

    async def append_audio(self, audio: str) -> None:
        """Caller audio (base64), in the provider's `audio_format`."""

    async def respond(self) -> None:
        """Ask the model to answer the caller (it has heard the audio and the tool results)."""

    async def say(self, text: str) -> None:
        """Ask the model to say exactly `text`, with no tools: a canned or greeting reply."""

    async def cancel(self) -> None:
        """Stop the response being generated."""

    async def truncate(self, item_id: str, audio_end_ms: int) -> None:
        """Tell the model how much of a reply's audio the caller actually heard."""

    async def tool_result(self, call_id: str, output: str) -> None:
        """The answer to a `ToolCall`. It does not start a response: `respond` does."""

    async def receive(self) -> ModelEvent | None:
        """The next event, or None once the connection is closed."""

    async def close(self) -> None: ...


class VoiceModelProvider(Protocol):
    """A realtime voice model that can be connected to. Built by `VoiceModelBuilder`."""

    name: str  # "openai"
    model: str
    audio_format: AudioFormat  # what it takes and sends

    async def connect(self) -> VoiceModelConnection:
        """Open a session. Raises `VoiceModelError`."""
