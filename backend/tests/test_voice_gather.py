import logging
from urllib.parse import urlencode
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api.deps import get_voice_service
from app.api.routes.channels import include_channel_routers
from app.core.config import get_settings
from app.services import voice_twiml
from app.services.voice_service import APOLOGY
from tests.voice_fakes import BASE, CALLER, TOKEN, FakeChat, make_settings, make_voice

GATHER = f"{BASE}/api/channels/voice/gather"


def make_client(chat=None, max_call_seconds=600):
    settings = make_settings(voice_mode="gather", voice_max_call_seconds=max_call_seconds)
    voice = make_voice(chat, max_call_seconds=max_call_seconds)
    app = FastAPI()
    include_channel_routers(app, settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_voice_service] = lambda: voice.service
    call = voice.service.start_call(CALLER, "CA1")
    return TestClient(app), voice, call


def post(client, query, form=None, signed_url=None, signature=None):
    form = {"CallSid": "CA1", "From": CALLER} if form is None else form
    suffix = f"?{query}" if query else ""
    if signature is None:
        signature = RequestValidator(TOKEN).compute_signature(signed_url or GATHER + suffix, form)
    return client.post(
        "/api/channels/voice/gather" + suffix,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        },
    )


def parse(response) -> ElementTree.Element:
    assert response.headers["content-type"].startswith("application/xml")
    return ElementTree.fromstring(response.text.split("?>", 1)[1])


def tags(root) -> list[str]:
    return [child.tag for child in root]


def test_speech_runs_a_turn_and_the_reply_is_spoken_before_listening_again():
    chat = FakeChat("**Sure.** See [pricing](https://example.com/p).")
    client, voice, call = make_client(chat)

    response = post(client, f"c={call.conversation_id}", {"CallSid": "CA1", "SpeechResult": "hi"})

    assert chat.calls == [(call.conversation_id, "hi", call.visitor_id, "voice")]
    root = parse(response)
    gather = root.find("Gather")
    assert gather.get("action") == f"{GATHER}?c={call.conversation_id}"
    assert gather.get("input") == "speech"
    assert gather.find("Say").text == "Sure. See pricing. No links aloud."
    assert root.find("Redirect") is not None
    assert voice.flushed == [1]


def test_the_number_sent_by_twilio_is_never_stored_or_spoken():
    chat = FakeChat()
    client, voice, call = make_client(chat)
    response = post(
        client,
        f"c={call.conversation_id}",
        {"CallSid": "CA1", "From": CALLER, "SpeechResult": "hi"},
    )
    assert "600123456" not in response.text
    assert "600123456" not in repr(chat.calls)


def test_a_failing_turn_is_apologised_and_the_call_goes_on():
    client, _, call = make_client(FakeChat(error=RuntimeError("boom")))
    root = parse(post(client, f"c={call.conversation_id}", {"SpeechResult": "hi"}))
    assert root.find("Gather/Say").text == APOLOGY
    assert root.find("Redirect") is not None


def test_silence_is_reprompted_once_then_the_call_ends():
    chat = FakeChat()
    client, _, call = make_client(chat)

    first = parse(post(client, f"c={call.conversation_id}", {"CallSid": "CA1"}))
    assert first.find("Gather/Say").text == voice_twiml.DIDNT_CATCH
    again = f"{GATHER}?c={call.conversation_id}&r=1"
    assert first.find("Gather").get("action") == again
    assert first.find("Redirect").text == again

    second = parse(post(client, f"c={call.conversation_id}&r=1", {"CallSid": "CA1"}))
    assert tags(second) == ["Say", "Hangup"]
    assert second.find("Say").text == voice_twiml.NO_INPUT_GOODBYE
    assert chat.calls == []  # silence never reaches the agent


def test_blank_speech_counts_as_silence():
    client, _, call = make_client()
    root = parse(post(client, f"c={call.conversation_id}", {"SpeechResult": "   "}))
    assert root.find("Gather/Say").text == voice_twiml.DIDNT_CATCH


def test_speech_after_a_reprompt_is_answered_normally():
    chat = FakeChat("fine")
    client, _, call = make_client(chat)
    root = parse(post(client, f"c={call.conversation_id}&r=1", {"SpeechResult": "hello"}))
    assert root.find("Gather/Say").text == "fine"
    assert root.find("Gather").get("action") == f"{GATHER}?c={call.conversation_id}"  # reset


def test_an_unknown_conversation_is_a_safe_hang_up_and_opens_nothing(caplog):
    chat = FakeChat()
    client, voice, _ = make_client(chat)
    before = dict(voice.repo.rows)
    for query in (f"c={uuid4()}", "c=not-a-uuid", ""):
        with caplog.at_level(logging.WARNING):
            root = parse(post(client, query, {"CallSid": "CA1", "SpeechResult": "hi"}))
        assert tags(root) == ["Say", "Hangup"]
    assert chat.calls == []
    assert voice.repo.rows == before


def test_a_conversation_of_another_channel_is_a_safe_hang_up():
    chat = FakeChat()
    client, voice, _ = make_client(chat)
    other = voice.repo.get_or_create(None, uuid4(), "whatsapp")
    root = parse(post(client, f"c={other.id}", {"SpeechResult": "hi"}))
    assert tags(root) == ["Say", "Hangup"]
    assert chat.calls == []


def test_the_signature_covers_the_query_string():
    client, _, call = make_client()
    form = {"CallSid": "CA1", "SpeechResult": "hi"}
    query = f"c={call.conversation_id}"
    # Signed for the URL without the query, or for another conversation: both are forgeries.
    assert post(client, query, form, signed_url=GATHER).status_code == 403
    assert post(client, query, form, signed_url=f"{GATHER}?c={uuid4()}").status_code == 403
    assert post(client, query, form, signature="bad").status_code == 403
    assert post(client, query, form).status_code == 200


def test_a_call_past_the_time_limit_is_ended_with_a_goodbye():
    chat = FakeChat()
    client, voice, call = make_client(chat, max_call_seconds=60)
    voice.clock.elapsed = 61
    root = parse(post(client, f"c={call.conversation_id}", {"SpeechResult": "hi"}))
    assert tags(root) == ["Say", "Hangup"]
    assert root.find("Say").text == voice_twiml.TIME_UP
    assert chat.calls == []


def test_a_long_reply_is_cut_to_what_say_accepts():
    client, _, call = make_client(FakeChat("A sentence goes here. " * 400))
    root = parse(post(client, f"c={call.conversation_id}", {"SpeechResult": "hi"}))
    said = root.find("Gather/Say").text
    assert len(said) <= voice_twiml.MAX_SAY_CHARS and said.endswith(".")
