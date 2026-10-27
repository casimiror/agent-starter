"""VoiceModelBuilder and VoiceModelFactory: what a provider declares, what build() checks, what the
settings pick. No sockets."""

from typing import ClassVar

import pytest

from app.clients.voice_models.base import MULAW_8K, AudioFormat, VoiceModelConfig
from app.clients.voice_models.builder import VoiceModelBuilder
from app.clients.voice_models.factory import VoiceModelFactory
from app.clients.voice_models.openai import OpenAIRealtimeProvider
from app.core.config import Settings

PCM_16K = AudioFormat("pcm16", 16000)


class StubProvider:
    """A provider as a module in this package would declare one."""

    name: ClassVar[str] = "stub"
    required: ClassVar[tuple[str, ...]] = ("model", "api_key", "voice")
    api_key_setting: ClassVar[str] = "llm_api_key"
    api_key_env: ClassVar[str] = "LLM_API_KEY"
    voices: ClassVar[frozenset[str] | None] = frozenset({"aria", "ben"})
    audio_format = PCM_16K

    def __init__(self, config: VoiceModelConfig) -> None:
        self.config = config
        self.model = config.model


@pytest.fixture
def stub_registered():
    VoiceModelFactory.register("stub", StubProvider)
    yield
    VoiceModelFactory.registry().pop("stub", None)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


# --- the builder ------------------------------------------------------------------------------


def test_the_builder_collects_the_fields_and_builds_the_provider():
    provider = (
        VoiceModelBuilder("openai")
        .with_model("gpt-realtime-2.1")
        .with_api_key("sk-test")
        .with_voice("marin")
        .with_language("en-US")
        .with_transcription_model("gpt-4o-mini-transcribe")
        .with_turn_detection(create_response=False, interrupt_response=False)
        .with_endpoint("ws://localhost:1/v1/realtime")
        .build()
    )
    assert isinstance(provider, OpenAIRealtimeProvider)
    assert provider.model == "gpt-realtime-2.1"
    assert provider.audio_format == MULAW_8K
    config = provider._config
    assert (config.api_key, config.voice, config.language) == ("sk-test", "marin", "en-US")
    assert config.transcription_model == "gpt-4o-mini-transcribe"
    assert config.turn_detection.interrupt_response is False
    assert config.endpoint == "ws://localhost:1/v1/realtime"


def test_build_names_every_missing_required_field():
    with pytest.raises(ValueError) as error:
        VoiceModelBuilder("openai").with_model("gpt-realtime-2.1").build()
    message = str(error.value)
    assert "'openai'" in message
    assert "an API key" in message and "a voice" in message and "a transcription model" in message
    assert "with_model)" not in message  # the model was set


def test_the_api_key_is_not_in_the_config_repr():
    assert "sk-secret" not in repr(VoiceModelConfig(api_key="sk-secret"))


def test_the_builder_rejects_an_unknown_provider():
    with pytest.raises(ValueError, match="unknown voice model provider 'gemini'"):
        VoiceModelBuilder("gemini")


def test_a_provider_that_declares_its_voices_rejects_others(stub_registered):
    builder = VoiceModelBuilder("stub").with_model("m").with_api_key("k")
    with pytest.raises(ValueError, match="voice 'zed'"):
        builder.with_voice("zed").build()
    assert builder.with_voice("aria").build().config.voice == "aria"


def test_a_provider_that_does_not_need_a_field_builds_without_it(stub_registered):
    provider = VoiceModelBuilder("stub").with_model("m").with_api_key("k").with_voice("ben").build()
    assert provider.audio_format == PCM_16K  # the bridge, not the builder, handles the format


# --- the factory ------------------------------------------------------------------------------


def test_the_factory_has_openai_registered():
    assert VoiceModelFactory.registry()["openai"] is OpenAIRealtimeProvider


def test_from_settings_builds_the_provider_the_settings_describe():
    (provider,) = VoiceModelFactory.from_settings(
        settings(
            openai_api_key="sk-test",
            voice_realtime_model="gpt-realtime-2.1-mini",
            voice_realtime_voice="cedar",
            voice_realtime_transcription_model="whisper-1",
        )
    )
    assert isinstance(provider, OpenAIRealtimeProvider)
    assert provider.model == "gpt-realtime-2.1-mini"
    config = provider._config
    assert (config.api_key, config.voice) == ("sk-test", "cedar")
    assert config.transcription_model == "whisper-1"


def test_from_settings_without_the_key_is_a_clear_error():
    with pytest.raises(ValueError, match="an API key"):
        VoiceModelFactory.from_settings(settings())


def test_a_registered_provider_is_picked_by_the_setting(stub_registered):
    (provider,) = VoiceModelFactory.from_settings(
        settings(voice_realtime_provider="stub", llm_api_key="k", voice_realtime_voice="aria")
    )
    assert isinstance(provider, StubProvider)
    assert provider.config.api_key == "k"  # the key setting the provider declared


def test_an_unknown_provider_stops_the_app_at_startup():
    with pytest.raises(ValueError, match="unknown voice model provider"):
        settings(voice_realtime_provider="gemini")
    with pytest.raises(ValueError, match="use one of"):
        VoiceModelFactory.provider_class("gemini")


# --- fallbacks --------------------------------------------------------------------------------


def with_fallbacks(*entries, **values):
    return VoiceModelFactory.from_settings(
        settings(
            openai_api_key="sk-test",
            llm_api_key="k",
            voice_realtime_fallbacks=list(entries),
            **values,
        )
    )


def test_without_fallbacks_there_is_only_the_primary():
    assert len(with_fallbacks()) == 1


def test_the_primary_comes_first_then_each_fallback_in_order():
    models = with_fallbacks("openai:gpt-realtime-2.1-mini", "openai:gpt-realtime-2.2:ash")
    assert [m.model for m in models] == [
        "gpt-realtime-2.1",
        "gpt-realtime-2.1-mini",
        "gpt-realtime-2.2",
    ]


def test_a_fallback_on_the_same_provider_keeps_the_voice():
    models = with_fallbacks("openai:gpt-realtime-2.1-mini", voice_realtime_voice="cedar")
    assert [m._config.voice for m in models] == ["cedar", "cedar"]


def test_a_fallback_can_name_its_own_voice_on_the_same_provider():
    models = with_fallbacks("openai:gpt-realtime-2.1-mini:ash")
    assert models[1]._config.voice == "ash"


def test_a_voice_the_provider_does_not_have_stops_the_app_at_startup():
    with pytest.raises(ValueError, match="voice 'zed'"):
        with_fallbacks("openai:gpt-realtime-2.1-mini:zed")


def test_a_fallback_on_another_provider_must_name_its_voice(stub_registered):
    with pytest.raises(ValueError, match="name one"):
        with_fallbacks("stub:s-1")


def test_a_fallback_on_another_provider_uses_the_voice_it_names(stub_registered):
    primary, other = with_fallbacks("stub:s-1:aria")
    assert (primary._config.voice, other.config.voice) == ("marin", "aria")
    assert other.config.api_key == "k"  # that provider's own key setting


def test_that_voice_must_exist_on_that_provider(stub_registered):
    with pytest.raises(ValueError, match="voice 'marin'"):
        with_fallbacks("stub:s-1:marin")


@pytest.mark.parametrize(
    "entry", ["gpt-realtime-2.1", "openai:", ":model", "openai:m:v:extra", "openai::ash", ""]
)
def test_a_malformed_fallback_entry_stops_the_app_at_startup(entry):
    with pytest.raises(ValueError, match="must be 'provider:model'"):
        with_fallbacks(entry)


def test_a_fallback_on_an_unknown_provider_stops_the_app_at_startup():
    with pytest.raises(ValueError, match="unknown voice model provider 'gemini'"):
        with_fallbacks("gemini:live:aoede")


def test_a_fallback_whose_key_is_missing_stops_the_app_at_startup(stub_registered):
    with pytest.raises(ValueError, match="an API key"):
        VoiceModelFactory.from_settings(
            settings(
                openai_api_key="sk-test", llm_api_key="", voice_realtime_fallbacks=["stub:s-1:aria"]
            )
        )
