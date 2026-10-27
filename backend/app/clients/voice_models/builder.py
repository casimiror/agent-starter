"""`VoiceModelBuilder`: one realtime voice model, configured fluently and validated on `build()`.

    provider = (
        VoiceModelBuilder("openai")
        .with_model("gpt-realtime-2.1")
        .with_api_key(key)
        .with_voice("marin")
        .with_transcription_model("gpt-4o-mini-transcribe")
        .build()
    )

Each provider class declares what it needs (`required`) and supports (`voices`, `audio_format`);
`build()` checks the collected values against that and raises a `ValueError` that names what is
missing, so a bad setup stops the app at startup and not on the first call. This builds the
*model*; the agent (prompt, tools, guardrails) is defined once, in `AgentBuilder`'s sources, and
shared with every other channel.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Self

from app.clients.voice_models.base import TurnDetection, VoiceModelConfig, VoiceModelProvider

# Config field -> the setting a person sets, for error messages that say where to fix it.
_FIELD_LABELS = {
    "model": "a model (with_model)",
    "api_key": "an API key (with_api_key)",
    "voice": "a voice (with_voice)",
    "transcription_model": "a transcription model (with_transcription_model)",
    "language": "a language (with_language)",
}


class VoiceModelBuilder:
    def __init__(self, provider: str, registry: Mapping[str, Any] | None = None) -> None:
        if registry is None:
            # Late: the factory imports this module for `from_settings`.
            from app.clients.voice_models.factory import VoiceModelFactory

            registry = VoiceModelFactory.registry()
        if provider not in registry:
            raise ValueError(
                f"unknown voice model provider {provider!r}: use one of {sorted(registry)}"
            )
        self._provider = provider
        self._cls = registry[provider]
        self._config = VoiceModelConfig()

    def with_model(self, model: str) -> Self:
        self._config = replace(self._config, model=model)
        return self

    def with_api_key(self, api_key: str) -> Self:
        self._config = replace(self._config, api_key=api_key)
        return self

    def with_voice(self, voice: str) -> Self:
        self._config = replace(self._config, voice=voice)
        return self

    def with_language(self, language: str) -> Self:
        self._config = replace(self._config, language=language)
        return self

    def with_transcription_model(self, transcription_model: str) -> Self:
        self._config = replace(self._config, transcription_model=transcription_model)
        return self

    def with_turn_detection(
        self, create_response: bool = False, interrupt_response: bool = True
    ) -> Self:
        """How the server detects the caller's turns. The bridge answers every turn itself (after
        the input guardrails), so leave `create_response` off unless you change the bridge."""
        detection = TurnDetection(create_response, interrupt_response)
        self._config = replace(self._config, turn_detection=detection)
        return self

    def with_endpoint(self, endpoint: str) -> Self:
        """Another URL for the same provider (a regional or Azure endpoint, a local test server)."""
        self._config = replace(self._config, endpoint=endpoint)
        return self

    def build(self) -> VoiceModelProvider:
        missing = [
            _FIELD_LABELS.get(name, name)
            for name in self._cls.required
            if not getattr(self._config, name)
        ]
        if missing:
            raise ValueError(f"voice model provider {self._provider!r} needs {', '.join(missing)}")
        voices = self._cls.voices
        if voices is not None and self._config.voice and self._config.voice not in voices:
            raise ValueError(
                f"voice {self._config.voice!r} is not one of {self._provider!r}'s: {sorted(voices)}"
            )
        return self._cls(self._config)
