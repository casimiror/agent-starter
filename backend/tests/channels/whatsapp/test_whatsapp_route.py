from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api.deps import get_whatsapp_dedupe, get_whatsapp_service
from app.api.routes.channels import include_channel_routers
from app.core.config import Settings, get_settings
from app.core.dedupe import RecentIds

TOKEN = "twilio-token"
BASE = "https://bot.example.com"
URL = f"{BASE}/api/channels/whatsapp/webhook"
FORM = {
    "From": "whatsapp:+34600123456",
    "To": "whatsapp:+14155238886",
    "Body": "hello there",
    "MessageSid": "SM1",
    "NumMedia": "0",
}


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def handle_message(self, sender, to, body, num_media, message_sid):
        self.calls.append((sender, to, body, num_media, message_sid))


def _settings(**values) -> Settings:
    return Settings(
        _env_file=None,
        channels=["web", "whatsapp"],
        channel_id_secret="s",
        public_base_url=values.pop("public_base_url", BASE),
        twilio_account_sid="AC1",
        twilio_auth_token=TOKEN,
        **values,
    )


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(service):
    app = FastAPI()
    settings = _settings()
    include_channel_routers(app, settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_whatsapp_service] = lambda: service
    dedupe = RecentIds()
    app.dependency_overrides[get_whatsapp_dedupe] = lambda: dedupe
    return TestClient(app)


def _post(client, form=None, url=URL, token=TOKEN, signature=None, **kwargs):
    form = FORM if form is None else form
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if signature is None:
        signature = RequestValidator(token).compute_signature(url, form)
    headers["X-Twilio-Signature"] = signature
    return client.post(
        "/api/channels/whatsapp/webhook", content=urlencode(form), headers=headers, **kwargs
    )


def test_a_valid_call_answers_with_empty_twiml_and_schedules_the_turn(client, service):
    response = _post(client)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text == '<?xml version="1.0" encoding="UTF-8"?><Response/>'
    assert service.calls == [
        ("whatsapp:+34600123456", "whatsapp:+14155238886", "hello there", 0, "SM1")
    ]


def test_media_is_passed_on_as_a_count(client, service):
    _post(client, {**FORM, "NumMedia": "2", "MessageSid": "SM2"})
    assert service.calls[0][3] == 2


def test_a_bad_signature_is_403_and_nothing_runs(client, service):
    assert _post(client, signature="bad").status_code == 403
    assert _post(client, token="other-token").status_code == 403
    assert service.calls == []


def test_a_missing_signature_is_403(client, service):
    response = client.post(
        "/api/channels/whatsapp/webhook",
        content=urlencode(FORM),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 403
    assert service.calls == []


def test_the_signature_is_checked_against_the_public_url_not_the_request_url(client, service):
    wrong = "http://testserver/api/channels/whatsapp/webhook"  # what request.url looks like here
    assert _post(client, url=wrong).status_code == 403
    assert _post(client, url=URL).status_code == 200


def test_the_body_is_part_of_the_signature(client, service):
    sig = RequestValidator(TOKEN).compute_signature(URL, FORM)
    tampered = {**FORM, "Body": "something else"}
    assert _post(client, tampered, signature=sig).status_code == 403


def test_a_body_over_64kb_is_413_by_content_length(client, service):
    huge = {**FORM, "Body": "x" * (65 * 1024)}
    assert _post(client, huge).status_code == 413
    assert service.calls == []


def test_a_streamed_body_over_64kb_is_413_without_a_content_length(client, service):
    def chunks():
        for _ in range(70):
            yield b"Body=" + b"x" * 1024 + b"&"

    response = client.post(
        "/api/channels/whatsapp/webhook",
        content=chunks(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    assert service.calls == []


@pytest.mark.parametrize("missing", ["From", "MessageSid"])
def test_a_missing_from_or_message_sid_is_400(client, service, missing):
    form = {k: v for k, v in FORM.items() if k != missing}
    assert _post(client, form).status_code == 400
    assert service.calls == []


def test_the_same_message_sid_twice_is_processed_once(client, service):
    first, second = _post(client), _post(client)
    assert first.status_code == second.status_code == 200
    assert second.text == first.text
    assert len(service.calls) == 1


def test_different_message_sids_are_both_processed(client, service):
    _post(client)
    _post(client, {**FORM, "MessageSid": "SM2"})
    assert len(service.calls) == 2


def test_a_trailing_slash_in_the_public_base_url_is_ignored(service):
    app = FastAPI()
    settings = _settings(public_base_url=BASE + "/")
    include_channel_routers(app, settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_whatsapp_service] = lambda: service
    app.dependency_overrides[get_whatsapp_dedupe] = lambda: RecentIds()
    assert _post(TestClient(app)).status_code == 200


def test_the_router_is_not_mounted_without_whatsapp_in_channels():
    app = FastAPI()
    mounted = include_channel_routers(app, Settings(_env_file=None, channels=["web"]))
    assert mounted == []
    response = TestClient(app).post("/api/channels/whatsapp/webhook", content=b"")
    assert response.status_code == 404


def test_recent_ids_forget_after_the_ttl_and_cap_their_size():
    now = [0.0]
    ids = RecentIds(ttl=10, max_size=2, clock=lambda: now[0])
    assert not ids.seen_before("a")
    assert ids.seen_before("a")
    now[0] = 11
    assert not ids.seen_before("a")  # expired
    assert not ids.seen_before("b")
    assert not ids.seen_before("c")  # evicts the oldest to stay at max_size
    assert not ids.seen_before("a")
