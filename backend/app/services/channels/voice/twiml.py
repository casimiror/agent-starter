"""The TwiML documents of the voice channel. Pure functions: settings in, XML string out.

Built with the Twilio SDK's `VoiceResponse`, which escapes attribute values and text. Nothing here
takes a phone number: the only identifiers in a document are the anonymous visitor id and the
conversation id.
"""

from collections.abc import Callable
from urllib.parse import urlencode, urlparse
from uuid import UUID

from twilio.twiml.voice_response import VoiceResponse

from app.core.config import Settings
from app.services.channels.voice.format import truncate_speech

INCOMING_PATH = "/api/channels/voice/incoming"
RELAY_WS_PATH = "/api/channels/voice/relay/ws"
RELAY_ACTION_PATH = "/api/channels/voice/relay/action"
GATHER_PATH = "/api/channels/voice/gather"
STREAM_PATH = "/api/channels/voice/stream"

# Twilio's <Say> rejects more than 4096 characters.
MAX_SAY_CHARS = 3500

TOO_MANY_CALLS = "You've called a few times in a row. Please try again in a minute. Goodbye."
SOMETHING_WRONG = "Sorry, something went wrong on my side. Please call again in a moment. Goodbye."
DIDNT_CATCH = "Sorry, I didn't catch that. Could you say it again?"
NO_INPUT_GOODBYE = "I still can't hear you, so I'll hang up. Goodbye."
TIME_UP = "We've reached the time limit for this call. Thanks for calling. Goodbye."


def relay_ws_url(settings: Settings) -> str:
    """The wss URL ConversationRelay connects to: same host as PUBLIC_BASE_URL."""
    return "wss://" + urlparse(settings.public_base_url).netloc + RELAY_WS_PATH


def stream_url(settings: Settings) -> str:
    """The wss URL Media Streams connects to. No query string (Twilio rejects one): what the
    socket needs travels as a <Parameter>."""
    return "wss://" + urlparse(settings.public_base_url).netloc + STREAM_PATH


def gather_url(settings: Settings, conversation_id: UUID, empty_inputs: int = 0) -> str:
    """Where a <Gather> posts. The conversation travels in the query string (a UUID, not PII).
    Twilio signs the full URL including the query, so the route validates the exact string
    emitted here; `r` counts the silences so far, which is how the route knows to hang up."""
    query = {"c": str(conversation_id), **({"r": str(empty_inputs)} if empty_inputs else {})}
    return settings.public_base_url.rstrip("/") + GATHER_PATH + "?" + urlencode(query)


def _doc(response: VoiceResponse) -> str:
    return str(response)


def say_and_hang_up(settings: Settings, message: str) -> str:
    response = VoiceResponse()
    response.say(message, language=settings.voice_language)
    response.hangup()
    return _doc(response)


def gather_say(settings: Settings, text: str, conversation_id: UUID, empty_inputs: int = 0) -> str:
    """Say `text` and listen. The <Say> is inside the <Gather>, so the caller can talk over it.
    When nothing is heard Twilio falls through to the <Redirect>, which lands on the same URL as
    the <Gather> action so silence is handled in one place (the gather route)."""
    url = gather_url(settings, conversation_id, empty_inputs)
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        action=url,
        method="POST",
        speech_timeout="auto",
        language=settings.voice_language,
    )
    gather.say(truncate_speech(text, MAX_SAY_CHARS), language=settings.voice_language)
    response.redirect(url, method="POST")
    return _doc(response)


def incoming_gather(settings: Settings, visitor_id: UUID, conversation_id: UUID) -> str:
    return gather_say(settings, settings.voice_greeting, conversation_id)


def incoming_relay(settings: Settings, visitor_id: UUID, conversation_id: UUID) -> str:
    """Hand the call to ConversationRelay: Twilio listens (STT) and speaks (TTS) and exchanges
    text with our WebSocket. The two ids reach it as `customParameters` in the `setup` message."""
    response = VoiceResponse()
    connect = response.connect(action=settings.public_base_url.rstrip("/") + RELAY_ACTION_PATH)
    options = {
        "url": relay_ws_url(settings),
        "welcome_greeting": settings.voice_greeting,
        "language": settings.voice_language,
        "tts_provider": settings.voice_tts_provider,
        "transcription_provider": settings.voice_transcription_provider,
        "interruptible": "any",
    }
    if settings.voice_voice:
        options["voice"] = settings.voice_voice
    relay = connect.conversation_relay(**options)
    relay.parameter(name="visitor_id", value=str(visitor_id))
    relay.parameter(name="conversation_id", value=str(conversation_id))
    return _doc(response)


def incoming_realtime(settings: Settings, visitor_id: UUID, conversation_id: UUID) -> str:
    """Fork the call's audio to our WebSocket (Media Streams, bidirectional). Twilio runs no
    further TwiML until the stream closes. Only the conversation id is passed: the socket
    finds the visitor from the stored conversation."""
    response = VoiceResponse()
    stream = response.connect().stream(url=stream_url(settings))
    stream.parameter(name="conversation_id", value=str(conversation_id))
    return _doc(response)


# mode -> builder of the document that answers "a call comes in". A new mode adds a line here, its
# value in `Settings.voice_mode` and its own routes in app/api/routes/channels/.
IncomingBuilder = Callable[[Settings, UUID, UUID], str]
INCOMING: dict[str, IncomingBuilder] = {
    "relay": incoming_relay,
    "gather": incoming_gather,
    "realtime": incoming_realtime,
}


def hang_up() -> str:
    response = VoiceResponse()
    response.hangup()
    return _doc(response)
