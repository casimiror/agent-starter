"""Audio between Twilio and the voice model.

Twilio Media Streams carries mu-law at 8 kHz. A provider whose `audio_format` is the same needs
nothing (`PassthroughTranscoder`, today's only case). Any other format needs a transcoder that
converts both ways; none is implemented, so `transcoder_for` refuses it at the start of the call
rather than sending the model audio it would misread. To support one, write the transcoder (no
`audioop`: it is gone from Python 3.13) and return it here.
"""

from typing import Protocol

from app.clients.voice_models.base import MULAW_8K, AudioFormat

TWILIO_FORMAT = MULAW_8K


class AudioTranscoder(Protocol):
    def to_model(self, audio: str) -> str:
        """A base64 chunk from Twilio, in the model's format."""

    def to_twilio(self, audio: str) -> str:
        """A base64 chunk from the model, in Twilio's format."""


class PassthroughTranscoder:
    def to_model(self, audio: str) -> str:
        return audio

    def to_twilio(self, audio: str) -> str:
        return audio


def transcoder_for(model_format: AudioFormat) -> AudioTranscoder:
    """The transcoder between Twilio's format and `model_format`. Raises NotImplementedError when
    they differ: only the passthrough exists."""
    if model_format == TWILIO_FORMAT:
        return PassthroughTranscoder()
    raise NotImplementedError(
        f"no transcoder between Twilio's {TWILIO_FORMAT.encoding} {TWILIO_FORMAT.sample_rate} Hz "
        f"and {model_format.encoding} {model_format.sample_rate} Hz: add one in "
        "services/channels/voice/realtime/audio.py (docs/channels.md)"
    )
