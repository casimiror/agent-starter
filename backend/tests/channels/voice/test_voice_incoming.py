from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api.deps import get_voice_service
from app.api.routes.channels import include_channel_routers
from app.core.config import get_settings
from tests.channels.voice.voice_fakes import (
    BASE,
    CALLER,
    CALLER_NAME,
    TOKEN,
    FakeChat,
    make_settings,
    make_voice,
)

URL = f"{BASE}/api/channels/voice/incoming"
FORM = {
    "CallSid": "CA1",
    "From": CALLER,
    "To": "+14155238886",
    "CallerName": CALLER_NAME,
    "CallStatus": "ringing",
}


def make_client(mode="relay", hit=None, **settings_values):
    settings = make_settings(voice_mode=mode, **settings_values)
    voice = make_voice(hit=hit)
    app = FastAPI()
    include_channel_routers(app, settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_voice_service] = lambda: voice.service
    return TestClient(app), voice, settings


def post(client, form=None, url=URL, signature=None, path="/api/channels/voice/incoming"):
    form = FORM if form is None else form
    if signature is None:
        signature = RequestValidator(TOKEN).compute_signature(url, form)
    return client.post(
        path,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        },
    )


def parse(response) -> ElementTree.Element:
    assert response.headers["content-type"].startswith("application/xml")
    return ElementTree.fromstring(response.text.split("?>", 1)[1])


@pytest.fixture(params=["relay", "gather"])
def any_mode(request):
    return make_client(request.param)


# --- both modes -------------------------------------------------------------------------------


def test_a_bad_or_missing_signature_is_403_and_creates_nothing(any_mode):
    client, voice, _ = any_mode
    assert post(client, signature="bad").status_code == 403
    assert post(client, url="http://testserver/api/channels/voice/incoming").status_code == 403
    assert client.post("/api/channels/voice/incoming", content=urlencode(FORM)).status_code == 403
    assert voice.repo.rows == {}


def test_a_body_over_64kb_is_413(any_mode):
    client, voice, _ = any_mode
    assert post(client, {**FORM, "CallerName": "x" * (65 * 1024)}).status_code == 413
    assert voice.repo.rows == {}


def test_a_missing_call_sid_is_400(any_mode):
    client, _, _ = any_mode
    form = {k: v for k, v in FORM.items() if k != "CallSid"}
    assert post(client, form).status_code == 400


def test_the_caller_number_and_name_never_appear_in_the_twiml(any_mode):
    client, _, _ = any_mode
    text = post(client).text
    for personal in ("600123456", CALLER, CALLER_NAME, "Jane", "4155238886"):
        assert personal not in text


@pytest.mark.parametrize("mode", ["relay", "gather"])
def test_a_caller_over_the_limit_hears_a_message_and_is_hung_up(mode):
    client, voice, _ = make_client(mode, hit=lambda *_: False)
    root = parse(post(client))
    assert [child.tag for child in root] == ["Say", "Hangup"]
    assert "try again" in root[0].text
    assert voice.repo.rows == {}


def test_each_call_is_a_new_conversation(any_mode):
    client, voice, _ = any_mode
    post(client)
    post(client, {**FORM, "CallSid": "CA2"})
    assert len(voice.repo.rows) == 2
    assert {row.channel for row in voice.repo.rows.values()} == {"voice"}


def test_hidden_callers_are_not_lumped_into_one_visitor():
    keys: list[str] = []
    client, voice, _ = make_client(hit=lambda limit, channel, key: keys.append(key) or True)
    post(client, {**FORM, "From": "anonymous", "CallSid": "CA1"})
    post(client, {**FORM, "From": "+266696687", "CallSid": "CA2"})
    assert len(set(keys)) == 2


@pytest.mark.parametrize(
    "hidden",
    ["", "anonymous", "Restricted", "unavailable", "unknown", "+266696687", "+7378742833",
     "+86282452253", "+123", "34600123456", "client:alice"],
)  # fmt: skip
def test_any_from_that_is_not_a_real_number_is_keyed_by_the_call(hidden):
    keys: list[str] = []
    client, _, _ = make_client(hit=lambda limit, channel, key: keys.append(key) or True)
    post(client, {**FORM, "From": hidden, "CallSid": "CA1"})
    post(client, {**FORM, "From": hidden, "CallSid": "CA2"})
    assert len(set(keys)) == 2


def test_a_real_number_is_one_visitor_across_calls():
    keys: list[str] = []
    client, _, _ = make_client(hit=lambda limit, channel, key: keys.append(key) or True)
    post(client, {**FORM, "From": "+34600123456", "CallSid": "CA1"})
    post(client, {**FORM, "From": "+34600123456", "CallSid": "CA2"})
    assert len(set(keys)) == 1


def test_a_failing_start_is_a_spoken_apology_not_a_500():
    def broken(*_):
        raise RuntimeError("limiter storage down")

    client, _, _ = make_client(hit=broken)
    response = post(client)
    assert response.status_code == 200
    assert [child.tag for child in parse(response)] == ["Say", "Hangup"]


# --- relay ------------------------------------------------------------------------------------


def test_relay_connects_the_call_to_conversation_relay():
    client, voice, settings = make_client("relay")
    root = parse(post(client))
    (row,) = voice.repo.rows.values()

    connect = root.find("Connect")
    assert connect.get("action") == f"{BASE}/api/channels/voice/relay/action"
    relay = connect.find("ConversationRelay")
    assert relay.get("url") == "wss://bot.example.com/api/channels/voice/relay/ws"
    assert relay.get("welcomeGreeting") == settings.voice_greeting
    assert relay.get("language") == "en-US"
    assert relay.get("ttsProvider") == "ElevenLabs"
    assert relay.get("transcriptionProvider") == "Deepgram"
    assert relay.get("interruptible") == "any"
    assert relay.get("voice") is None  # the provider's default
    parameters = {p.get("name"): p.get("value") for p in relay.findall("Parameter")}
    assert parameters == {"visitor_id": str(row.visitor_id), "conversation_id": str(row.id)}


def test_relay_settings_reach_the_twiml_escaped():
    client, _, _ = make_client(
        "relay",
        voice_language="es-ES",
        voice_greeting='Hi & welcome <"you">',
        voice_tts_provider="Google",
        voice_voice="es-ES-Neural2-A",
        voice_transcription_provider="Google",
    )
    response = post(client)
    relay = parse(response).find("Connect/ConversationRelay")
    assert relay.get("language") == "es-ES"
    assert relay.get("welcomeGreeting") == 'Hi & welcome <"you">'  # round-trips through XML
    assert relay.get("ttsProvider") == "Google"
    assert relay.get("voice") == "es-ES-Neural2-A"
    assert relay.get("transcriptionProvider") == "Google"
    assert "Hi &amp; welcome" in response.text


def test_a_trailing_slash_in_the_base_url_does_not_double_up():
    client, _, _ = make_client("relay", public_base_url=BASE + "/")
    connect = parse(post(client)).find("Connect")
    assert connect.get("action") == f"{BASE}/api/channels/voice/relay/action"


# --- gather -----------------------------------------------------------------------------------


def test_gather_greets_and_listens_with_the_conversation_in_the_url():
    client, voice, settings = make_client("gather")
    root = parse(post(client))
    (row,) = voice.repo.rows.values()
    url = f"{BASE}/api/channels/voice/gather?c={row.id}"

    gather = root.find("Gather")
    assert gather.get("input") == "speech"
    assert gather.get("action") == url
    assert gather.get("method") == "POST"
    assert gather.get("speechTimeout") == "auto"
    assert gather.get("language") == "en-US"
    assert gather.find("Say").text == settings.voice_greeting
    assert gather.find("Say").get("language") == "en-US"
    # Nothing heard: Twilio falls through to the next verb, which comes back to the same route.
    redirect = root.find("Redirect")
    assert redirect.text == url and redirect.get("method") == "POST"


# --- mode gating ------------------------------------------------------------------------------


def test_the_routes_of_the_other_mode_answer_404():
    gather_client, _, _ = make_client("gather")
    action = f"{BASE}/api/channels/voice/relay/action"
    assert (
        post(
            gather_client, {"CallSid": "CA1"}, action, path="/api/channels/voice/relay/action"
        ).status_code
        == 404
    )

    relay_client, _, _ = make_client("relay")
    gather = f"{BASE}/api/channels/voice/gather?c=x"
    assert (
        post(
            relay_client, {"CallSid": "CA1"}, gather, path="/api/channels/voice/gather?c=x"
        ).status_code
        == 404
    )


def test_voice_is_not_mounted_without_the_channel():
    app = FastAPI()
    mounted = include_channel_routers(app, make_settings(channels=["web"]))
    assert mounted == []
    assert TestClient(app).post("/api/channels/voice/incoming").status_code == 404


def test_the_registry_has_a_builder_for_every_voice_mode():
    from app.core.config import Settings
    from app.services.channels.voice.twiml import INCOMING

    modes = Settings.model_fields["voice_mode"].annotation.__args__
    assert set(INCOMING) == set(modes)


def test_fake_chat_is_never_called_when_a_call_comes_in():
    client, voice, _ = make_client()
    post(client)
    assert isinstance(voice.chat, FakeChat) and voice.chat.calls == []
