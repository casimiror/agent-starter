import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {"channel_id_secret": "s", "public_base_url": "https://x.example"}


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_voice_defaults():
    s = _settings()
    assert s.voice_mode == "relay"
    assert s.voice_language == "en-US"
    assert s.rate_limit_voice == "5/minute"
    assert s.voice_max_call_seconds == 600
    assert s.voice_tts_provider == "ElevenLabs"
    assert s.voice_transcription_provider == "Deepgram"
    assert s.voice_voice == ""
    assert "links" in s.voice_link_phrase


def test_an_unknown_voice_mode_fails_at_startup(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "telepathy")
    with pytest.raises(ValidationError, match="VOICE_MODE|voice_mode"):
        _settings()


def test_the_mode_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("VOICE_MODE", "gather")
    assert _settings().voice_mode == "gather"


@pytest.mark.parametrize("field", ["voice_tts_provider", "voice_transcription_provider"])
def test_an_unknown_provider_fails_at_startup(field):
    with pytest.raises(ValidationError):
        _settings(**{field: "Nobody"})


def test_the_max_call_seconds_must_be_positive():
    with pytest.raises(ValidationError):
        _settings(voice_max_call_seconds=0)


def test_voice_needs_the_auth_token_and_the_channel_basics():
    with pytest.raises(RuntimeError, match="TWILIO_AUTH_TOKEN"):
        _settings(channels=["voice"], **BASE).check_channels()
    with pytest.raises(RuntimeError, match="CHANNEL_ID_SECRET and PUBLIC_BASE_URL"):
        _settings(channels=["voice"], twilio_auth_token="t").check_channels()
    _settings(channels=["voice"], twilio_auth_token="t", **BASE).check_channels()


def test_whatsapp_and_voice_name_the_auth_token_once():
    with pytest.raises(RuntimeError) as error:
        _settings(channels=["whatsapp", "voice"], **BASE).check_channels()
    assert str(error.value).count("TWILIO_AUTH_TOKEN") == 1


def test_voice_max_pending_turns_defaults_to_two():
    assert Settings(_env_file=None).voice_max_pending_turns == 2
