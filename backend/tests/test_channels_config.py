import importlib
import sys
import types

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.channels import _lazy, include_channel_routers
from app.core.config import Settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_channels_default_to_web_only(monkeypatch):
    monkeypatch.delenv("CHANNELS", raising=False)
    assert _settings().channels == ["web"]
    assert _settings().extra_channels == []


def test_channels_are_read_as_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("CHANNELS", " web, WhatsApp ,voice,whatsapp")
    settings = _settings()
    assert settings.channels == ["web", "whatsapp", "voice"]
    assert settings.extra_channels == ["whatsapp", "voice"]


def test_an_empty_channels_value_means_web(monkeypatch):
    monkeypatch.setenv("CHANNELS", "")
    assert _settings().channels == ["web"]


def test_an_unknown_channel_fails_at_startup(monkeypatch):
    monkeypatch.setenv("CHANNELS", "web,telegram")
    with pytest.raises(ValidationError, match="telegram"):
        _settings()


@pytest.mark.parametrize(
    ("values", "missing"),
    [
        ({}, "CHANNEL_ID_SECRET and PUBLIC_BASE_URL"),
        ({"channel_id_secret": "s"}, "PUBLIC_BASE_URL"),
        ({"public_base_url": "https://x.example"}, "CHANNEL_ID_SECRET"),
    ],
)
def test_a_non_web_channel_needs_the_secret_and_the_base_url(values, missing):
    with pytest.raises(RuntimeError, match=missing):
        _settings(channels=["web", "whatsapp"], **values).check_channels()


def test_channel_settings_are_not_needed_for_web_only():
    _settings(channels=["web"]).check_channels()


def test_a_fully_configured_channel_passes():
    _settings(
        channels=["voice"],
        channel_id_secret="s",
        public_base_url="https://x.example",
        twilio_auth_token="t",
    ).check_channels()


def test_create_app_refuses_to_start_with_a_broken_channel_config(monkeypatch):
    # app.frontend() needs a built UI unless this is set; importing app.main creates the app.
    monkeypatch.setenv("FASTAPI_ENV", "development")
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: _settings(channels=["web", "whatsapp"])
    )
    sys.modules.pop("app.main", None)
    try:
        with pytest.raises(RuntimeError, match="CHANNEL_ID_SECRET"):
            importlib.import_module("app.main")
    finally:
        sys.modules.pop("app.main", None)


def _router(path: str) -> APIRouter:
    router = APIRouter()
    router.get(path)(lambda: {})
    return router


def test_only_enabled_channels_are_mounted_and_loaded():
    loaded: list[str] = []

    def loader(name: str):
        def load() -> APIRouter:
            loaded.append(name)
            return _router(f"/{name}/hook")

        return load

    registry = {"whatsapp": loader("whatsapp"), "voice": loader("voice")}
    app = FastAPI()

    mounted = include_channel_routers(app, _settings(channels=["web", "whatsapp"]), registry)

    assert mounted == ["whatsapp"]
    assert loaded == ["whatsapp"]  # voice was never imported
    client = TestClient(app)
    assert client.get("/api/whatsapp/hook").status_code == 200
    assert client.get("/api/voice/hook").status_code == 404


def test_web_only_mounts_nothing():
    app = FastAPI()
    registry = {"whatsapp": lambda: pytest.fail("must not load")}
    assert include_channel_routers(app, _settings(), registry) == []


def test_an_enabled_channel_without_a_router_is_skipped_with_a_warning(caplog):
    with caplog.at_level("WARNING", logger="app.channels"):
        mounted = include_channel_routers(FastAPI(), _settings(channels=["voice"]), {})
    assert mounted == []
    assert caplog.records[0].channel == "voice"


def test_lazy_loader_imports_the_module_only_when_called(monkeypatch):
    module = types.ModuleType("fake_channel_module")
    module.router = _router("/fake")
    monkeypatch.setitem(sys.modules, "fake_channel_module", module)
    assert _lazy("fake_channel_module")() is module.router


def test_whatsapp_needs_the_twilio_credentials():
    base = {"channel_id_secret": "s", "public_base_url": "https://x.example"}
    with pytest.raises(RuntimeError, match="TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN"):
        _settings(channels=["whatsapp"], **base).check_channels()
    with pytest.raises(RuntimeError, match="TWILIO_AUTH_TOKEN"):
        _settings(channels=["whatsapp"], twilio_account_sid="AC1", **base).check_channels()
    _settings(
        channels=["whatsapp"], twilio_account_sid="AC1", twilio_auth_token="t", **base
    ).check_channels()


def test_voice_alone_does_not_need_the_account_sid():
    _settings(
        channels=["voice"],
        channel_id_secret="s",
        public_base_url="https://x.example",
        twilio_auth_token="t",
    ).check_channels()


def test_whatsapp_rate_limit_defaults_to_ten_a_minute():
    assert _settings().rate_limit_whatsapp == "10/minute"


@pytest.mark.parametrize(
    ("channel", "setting", "name"),
    [
        ("whatsapp", "rate_limit_whatsapp", "RATE_LIMIT_WHATSAPP"),
        ("voice", "rate_limit_voice", "RATE_LIMIT_VOICE"),
    ],
)
def test_a_bad_sender_limit_fails_at_startup(channel, setting, name):
    with pytest.raises(RuntimeError, match=name):
        _settings(
            channels=[channel],
            channel_id_secret="s",
            public_base_url="https://x.example",
            twilio_account_sid="AC1",
            twilio_auth_token="t",
            **{setting: "ten per minute"},
        ).check_channels()
