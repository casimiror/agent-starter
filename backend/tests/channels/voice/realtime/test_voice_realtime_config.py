import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "channel_id_secret": "s",
    "public_base_url": "https://x.example",
    "twilio_auth_token": "t",
}


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_realtime_defaults():
    s = _settings()
    assert s.voice_realtime_provider == "openai"
    assert s.voice_realtime_model == "gpt-realtime-2.1"
    assert s.voice_realtime_voice == "marin"
    assert s.voice_realtime_transcription_model == "gpt-4o-mini-transcribe"


def test_realtime_is_a_voice_mode(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "realtime")
    assert _settings().voice_mode == "realtime"


def test_an_unknown_realtime_provider_fails_at_startup():
    with pytest.raises(ValidationError):
        _settings(voice_realtime_provider="gemini")


def test_realtime_voice_needs_the_openai_key():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _settings(channels=["voice"], voice_mode="realtime", **BASE).check_channels()
    _settings(
        channels=["voice"], voice_mode="realtime", openai_api_key="sk-x", **BASE
    ).check_channels()


@pytest.mark.parametrize("mode", ["relay", "gather"])
def test_the_other_voice_modes_do_not_need_it(mode):
    _settings(channels=["voice"], voice_mode=mode, **BASE).check_channels()


def test_realtime_without_the_voice_channel_needs_nothing():
    _settings(voice_mode="realtime").check_channels()


def test_transcript_wait_defaults_to_1500_ms():
    assert Settings(_env_file=None).voice_realtime_transcript_wait_ms == 1500
