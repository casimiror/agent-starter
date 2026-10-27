import logging
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.api.deps import get_relay_clock, get_voice_service
from app.api.routes.channels import include_channel_routers
from app.core.config import get_settings
from app.services.voice_service import APOLOGY
from tests.voice_fakes import BASE, CALLER, TOKEN, FakeChat, make_settings, make_voice

WS_URL = "wss://bot.example.com/api/channels/voice/relay/ws"
PATH = "/api/channels/voice/relay/ws"


def sign(url=WS_URL, token=TOKEN) -> dict[str, str]:
    return {"X-Twilio-Signature": RequestValidator(token).compute_signature(url, {})}


def make_client(chat=None, mode="relay", max_call_seconds=600, **settings_values):
    settings = make_settings(
        voice_mode=mode, voice_max_call_seconds=max_call_seconds, **settings_values
    )
    voice = make_voice(chat, max_call_seconds=max_call_seconds)
    app = FastAPI()
    include_channel_routers(app, settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_voice_service] = lambda: voice.service
    app.dependency_overrides[get_relay_clock] = lambda: voice.clock.monotonic
    call = voice.service.start_call(CALLER, "CA1")
    return TestClient(app), voice, call


def setup_message(call, **extra):
    return {
        "type": "setup",
        "callSid": "CA1",
        "from": CALLER,
        "callerName": "Jane Doe",
        "customParameters": {
            "visitor_id": str(call.visitor_id),
            "conversation_id": str(call.conversation_id),
        },
        **extra,
    }


def prompt(text, last=True):
    return {"type": "prompt", "voicePrompt": text, "lang": "en-US", "last": last}


def test_setup_then_partial_then_final_prompt_runs_one_turn_and_replies_once():
    chat = FakeChat("**Hello** from the agent")
    client, voice, call = make_client(chat)

    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("what do", last=False))
        ws.send_json(prompt("what do you sell", last=True))
        reply = ws.receive_json()

    assert reply == {"type": "text", "token": "Hello from the agent", "last": True}
    assert chat.calls == [(call.conversation_id, "what do you sell", call.visitor_id, "voice")]
    assert voice.flushed == [1]


def test_links_in_the_reply_become_the_spoken_phrase():
    client, _, call = make_client(FakeChat("See [pricing](https://example.com/p)"))
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("prices?"))
        token = ws.receive_json()["token"]
    assert token == "See pricing No links aloud."
    assert "http" not in token


def test_a_failing_turn_is_a_spoken_apology_and_the_call_goes_on():
    chat = FakeChat(error=RuntimeError("boom"))
    client, _, call = make_client(chat)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("hello"))
        assert ws.receive_json() == {"type": "text", "token": APOLOGY, "last": True}
        chat.error = None
        ws.send_json(prompt("hello again"))
        assert ws.receive_json()["token"] == "All good"


def test_overlapping_prompts_never_run_two_turns_at_once():
    chat = FakeChat("done", delay=0.05)
    client, _, call = make_client(chat, voice_max_pending_turns=3)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        for text in ("one", "two", "three"):
            ws.send_json(prompt(text))
        replies = [ws.receive_json() for _ in range(3)]
    assert [r["token"] for r in replies] == ["done"] * 3
    assert chat.max_concurrent == 1
    assert [c[1] for c in chat.calls] == ["one", "two", "three"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Twilio-Signature": "bad"}, sign(token="another-token"), sign("wss://evil.test/x")],
)
def test_a_handshake_with_a_bad_signature_is_rejected(headers):
    client, _, _ = make_client()
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(PATH, headers=headers):
            pass
    assert rejected.value.code == 1008


def test_the_signature_is_checked_against_the_public_url_not_the_request_url():
    client, _, _ = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH, headers=sign("ws://testserver" + PATH)):
            pass


def test_a_signature_over_the_url_with_a_trailing_slash_is_accepted_too(caplog):
    client, _, call = make_client()
    with client.websocket_connect(PATH, headers=sign(WS_URL + "/")) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("hi"))
        assert ws.receive_json()["type"] == "text"


def test_the_relay_socket_is_refused_in_gather_mode():
    client, _, _ = make_client(mode="gather")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH, headers=sign()):
            pass


def test_the_call_ends_when_the_time_limit_passes():
    chat = FakeChat()
    client, voice, call = make_client(chat, max_call_seconds=60)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("first"))
        assert ws.receive_json()["type"] == "text"
        voice.clock.elapsed = 61
        ws.send_json(prompt("second"))
        assert ws.receive_json() == {"type": "end"}
        ws.send_json(prompt("third"))  # ignored once the session ended
    assert [c[1] for c in chat.calls] == ["first"]


def test_setup_for_an_unknown_or_foreign_conversation_ends_the_session():
    chat = FakeChat()
    client, voice, call = make_client(chat)
    web = voice.repo.get_or_create(None, uuid4(), "web")
    for conversation_id in (str(uuid4()), "nope", str(web.id), None):
        with client.websocket_connect(PATH, headers=sign()) as ws:
            ws.send_json(
                {"type": "setup", "customParameters": {"conversation_id": conversation_id}}
            )
            assert ws.receive_json() == {"type": "end"}
            ws.send_json(prompt("hello"))
    assert chat.calls == []


def test_a_prompt_before_setup_is_ignored():
    chat = FakeChat()
    client, _, call = make_client(chat)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(prompt("hello"))
        ws.send_json(setup_message(call))
        ws.send_json(prompt("hello"))
        assert ws.receive_json()["type"] == "text"
    assert len(chat.calls) == 1


def test_junk_messages_do_not_break_the_session():
    client, _, call = make_client()
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_text("not json")
        ws.send_text("[1, 2]")
        ws.send_json({"type": "mystery"})
        ws.send_json(setup_message(call))
        ws.send_json(prompt("hi"))
        assert ws.receive_json()["type"] == "text"


def test_interrupt_dtmf_and_error_are_logged_without_content(caplog):
    client, _, call = make_client()
    with caplog.at_level(logging.INFO):
        with client.websocket_connect(PATH, headers=sign()) as ws:
            ws.send_json(setup_message(call))
            ws.send_json(
                {
                    "type": "interrupt",
                    "utteranceUntilInterrupt": "the words the caller heard",
                    "durationUntilInterruptMs": 1500,
                }
            )
            ws.send_json({"type": "dtmf", "digit": "7"})
            ws.send_json({"type": "error", "description": "Invalid message"})
            ws.send_json(prompt("hi"))
            assert ws.receive_json()["type"] == "text"  # no reply to the three above

    messages = {r.message: r for r in caplog.records}
    assert messages["voice reply interrupted"].after_ms == 1500
    assert messages["voice reply interrupted"].call_sid == "CA1"
    assert "voice dtmf received" in messages
    assert messages["voice relay error"].description == "Invalid message"
    assert "the words the caller heard" not in caplog.text
    assert "digit" not in caplog.text and "'7'" not in caplog.text


def test_the_caller_number_and_name_never_reach_logs_or_the_agent(caplog):
    chat = FakeChat()
    client, _, call = make_client(chat)
    with caplog.at_level(logging.DEBUG):
        with client.websocket_connect(PATH, headers=sign()) as ws:
            ws.send_json(setup_message(call, forwardedFrom=CALLER, to="+14155238886"))
            ws.send_json(prompt("hi"))
            ws.receive_json()
    for personal in ("600123456", "Jane Doe"):
        assert personal not in caplog.text
        assert personal not in repr(chat.calls)


# --- the action URL ---------------------------------------------------------------------------

ACTION = "/api/channels/voice/relay/action"


def post_action(client, form, signature=None):
    if signature is None:
        signature = RequestValidator(TOKEN).compute_signature(BASE + ACTION, form)
    return client.post(
        ACTION,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        },
    )


def test_the_action_url_logs_how_the_session_ended_and_hangs_up(caplog):
    client, _, _ = make_client()
    form = {
        "CallSid": "CA1",
        "SessionStatus": "failed",
        "SessionDuration": "12",
        "ErrorCode": "64105",
        "From": CALLER,
    }
    with caplog.at_level(logging.INFO):
        response = post_action(client, form)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text.endswith("<Response><Hangup /></Response>")
    record = next(r for r in caplog.records if r.message == "voice relay session ended")
    assert (record.call_sid, record.session_status, record.error_code) == ("CA1", "failed", "64105")
    assert "600123456" not in caplog.text


def test_the_action_url_checks_the_signature_and_the_mode():
    client, _, _ = make_client()
    assert post_action(client, {"CallSid": "CA1"}, signature="bad").status_code == 403
    gather_client, _, _ = make_client(mode="gather")
    assert post_action(gather_client, {"CallSid": "CA1"}).status_code == 404


def _interrupt(heard="Our prices st"):
    return {"type": "interrupt", "utteranceUntilInterrupt": heard, "durationUntilInterruptMs": 900}


def test_an_interrupt_replaces_the_stored_reply_with_what_the_caller_heard():
    client, voice, call = make_client(FakeChat("Our prices start at ten euros a month."))
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("prices?"))
        ws.receive_json()
        ws.send_json(_interrupt())
        ws.send_json(prompt("ok"))  # the interrupt is handled before this turn runs
        ws.receive_json()
    contents = [(m[1], m[2]) for m in voice.repo.messages]
    assert contents[:2] == [("user", "prices?"), ("assistant", "Our prices st")]
    assert contents[2] == ("user", "ok")


def test_an_interrupt_stores_the_heard_text_when_the_reply_is_not_stored_yet():
    chat = FakeChat("Our prices start at ten euros a month.")
    client, voice, call = make_client(chat)
    chat.store = None  # the turn did not persist (yet)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("prices?"))
        ws.receive_json()
        ws.send_json(_interrupt())
        ws.send_json(prompt("ok"))
        ws.receive_json()
    assert [(m[1], m[2]) for m in voice.repo.messages] == [("assistant", "Our prices st")]


def test_an_interrupt_that_heard_nothing_leaves_a_placeholder_not_an_empty_message():
    client, voice, call = make_client()
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("hi"))
        ws.receive_json()
        ws.send_json(_interrupt(""))
        ws.send_json(prompt("again"))
        ws.receive_json()
    assert voice.repo.messages[1][2] == "…"


def test_an_interrupt_during_the_greeting_or_twice_changes_nothing_more():
    client, voice, call = make_client(FakeChat("Full reply here."))
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(_interrupt("Hello, thanks for"))  # the greeting is not a stored reply
        ws.send_json(prompt("hi"))
        ws.receive_json()
        ws.send_json(_interrupt("Full"))
        ws.send_json(_interrupt("Full reply"))  # a second one for the same reply is ignored
        ws.send_json(prompt("again"))
        ws.receive_json()
    assert [m[2] for m in voice.repo.messages] == ["hi", "Full", "again", "Full reply here."]


def test_a_second_setup_is_ignored_and_does_not_rebind_the_session(caplog):
    chat = FakeChat()
    client, voice, call = make_client(chat)
    other = voice.service.start_call("+34600999888", "CA2")
    with caplog.at_level(logging.WARNING):
        with client.websocket_connect(PATH, headers=sign()) as ws:
            ws.send_json(setup_message(call))
            ws.send_json(setup_message(other))
            ws.send_json(prompt("hi"))
            assert ws.receive_json()["type"] == "text"
    assert chat.calls[0][0] == call.conversation_id
    assert "voice setup ignored, already set up" in caplog.text


def test_prompts_beyond_the_pending_cap_are_dropped(caplog):
    chat = FakeChat("done", delay=0.2)
    client, _, call = make_client(chat, voice_max_pending_turns=2)
    with caplog.at_level(logging.WARNING):
        with client.websocket_connect(PATH, headers=sign()) as ws:
            ws.send_json(setup_message(call))
            for text in ("one", "two", "three", "four"):
                ws.send_json(prompt(text))
            replies = [ws.receive_json(), ws.receive_json()]
    assert [r["token"] for r in replies] == ["done", "done"]
    assert [c[1] for c in chat.calls] == ["one", "two"]
    assert "voice prompt dropped, too many pending" in caplog.text
    assert "three" not in caplog.text


def test_closing_the_socket_mid_turn_cancels_the_turns_cleanly():
    chat = FakeChat("done", delay=0.3)
    client, _, call = make_client(chat)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        ws.send_json(setup_message(call))
        ws.send_json(prompt("slow"))
    # Leaving the block closed the socket while the turn ran: the handler must have finished
    # (TestClient waits for it) instead of leaving a pending task behind.
    assert chat.calls[0][1] == "slow"
