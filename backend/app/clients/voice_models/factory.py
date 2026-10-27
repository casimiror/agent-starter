"""`VoiceModelFactory`: which voice model providers exist, and the ones the settings pick.

Adding a provider is one module in this package (a class with `name`, `required`, `voices`,
`api_key_setting`, `api_key_env`, `audio_format`, `connect()`) plus one line in `_REGISTRY` below.
"""

from typing import TYPE_CHECKING, Any

from app.clients.voice_models.builder import VoiceModelBuilder
from app.clients.voice_models.openai import OpenAIRealtimeProvider

if TYPE_CHECKING:
    from app.clients.voice_models.base import VoiceModelProvider
    from app.core.config import Settings

_REGISTRY: dict[str, Any] = {"openai": OpenAIRealtimeProvider}


class VoiceModelFactory:
    @staticmethod
    def registry() -> dict[str, Any]:
        return _REGISTRY

    @staticmethod
    def register(name: str, cls: Any) -> None:
        """Add (or replace) a provider. For tests and for code outside this package; a provider
        that ships with the app is a line in `_REGISTRY`."""
        _REGISTRY[name] = cls

    @staticmethod
    def provider_class(name: str) -> Any:
        """The provider class for `name`. Raises ValueError for an unknown one."""
        if name not in _REGISTRY:
            raise ValueError(
                f"unknown voice model provider {name!r}: use one of {sorted(_REGISTRY)}"
            )
        return _REGISTRY[name]

    @staticmethod
    def from_settings(settings: "Settings") -> "list[VoiceModelProvider]":
        """The models `VOICE_REALTIME_*` describe, in the order a call tries them: the primary,
        then each `VOICE_REALTIME_FALLBACKS` entry ("provider:model" or "provider:model:voice").
        Raises ValueError (unknown provider, malformed entry, a value a provider rejects): call
        it at startup.

        The voice stays the same whichever model answers. An entry without a voice inherits
        `VOICE_REALTIME_VOICE`, which its provider must have (the builder checks); an entry on
        another provider must name its voice, because the catalogs differ."""
        primary = settings.voice_realtime_provider
        models = [
            VoiceModelFactory._build(
                settings, primary, settings.voice_realtime_model, settings.voice_realtime_voice
            )
        ]
        for entry in settings.voice_realtime_fallbacks:
            parts = entry.split(":")
            if len(parts) not in (2, 3) or not all(part.strip() for part in parts):
                raise ValueError(
                    f"VOICE_REALTIME_FALLBACKS entry {entry!r} must be 'provider:model' or "
                    "'provider:model:voice'"
                )
            provider, model = parts[0].strip(), parts[1].strip()
            voice = parts[2].strip() if len(parts) == 3 else ""
            if not voice:
                if provider != primary:
                    raise ValueError(
                        f"VOICE_REALTIME_FALLBACKS entry {entry!r} is on another provider than "
                        f"{primary!r}, whose voices differ: name one, 'provider:model:voice'"
                    )
                voice = settings.voice_realtime_voice
            models.append(VoiceModelFactory._build(settings, provider, model, voice))
        return models

    @staticmethod
    def _build(settings: "Settings", provider: str, model: str, voice: str) -> "VoiceModelProvider":
        cls = VoiceModelFactory.provider_class(provider)
        return (
            VoiceModelBuilder(provider, _REGISTRY)
            .with_model(model)
            .with_api_key(getattr(settings, cls.api_key_setting))
            .with_voice(voice)
            .with_language(settings.voice_language)
            .with_transcription_model(settings.voice_realtime_transcription_model)
            .build()
        )
