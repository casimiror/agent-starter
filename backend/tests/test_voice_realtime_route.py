"""The Media Streams WebSocket through Starlette's TestClient: a signed handshake, Twilio's JSON
messages in, the fake OpenAI connection behind it. No real Twilio or OpenAI."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.api.deps import get_realtime_connector, get_realtime_voice_service
from app.api.routes.channels import include_channel_routers
from app.core.config import get_settings
from tests.realtime_fakes import FakeConnector, make_lookup_tool, make_realtime_service, wait_until
from tests.test_voice_realtime_session import (
    BLOCKED_INPUT_REPLY,
    INJECTION,
    SPEECH_STARTED,
    audio,
    call_args,
    created,
    done,
    heard,
    mark,
    media,
    pcm,
    words_done,
)
from tests.voice_fakes import CALLER, TOKEN

WS_URL = "wss://bot.example.com/api/channels/voice/stream"
PATH = "/api/channels/voice/stream"


def sign(url=WS_URL, token=TOKEN) -> dict[str, str]:
    return {"X-Twilio-Signature": RequestValidator(token).compute_signature(url, {})}


def make_client(mode="realtime", max_call_seconds=600, tools=None):
    ctx = make_realtime_service(tools, voice_mode=mode, voice_greeting="")
    # The setting is whole seconds; a test wants a fraction of one.
    ctx.settings.voice_max_call_seconds = max_call_seconds
    connector = FakeConnector()
    app = FastAPI()
    include_channel_routers(app, ctx.settings)
    app.dependency_overrides[get_settings] = lambda: ctx.settings
    app.dependency_overrides[get_realtime_voice_service] = lambda: ctx.service
    app.dependency_overrides[get_realtime_connector] = lambda: connector
    call = ctx.voice.service.start_call(CALLER, "CA1")
    return TestClient(app), ctx, connector, call


def start(call):
    return {
        "event": "start",
        "streamSid": "MZ1",
        "start": {
            "streamSid": "MZ1",
            "callSid": "CA1",
            "customParameters": {"conversation_id": str(call.conversation_id)},
        },
    }


def open_stream(client, connector, call, ws):
    ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
    ws.send_json(start(call))
    wait_until(lambda: "session.update" in connector.connection.types())
    connector.connection.push({"type": "session.updated"})
    time.sleep(0.1)  # nothing is sent in reply: give the app time to mark the session ready


# --- the handshake ----------------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, sign(token="other-token"), sign("wss://evil.example/x")])
def test_a_bad_or_missing_signature_is_rejected_before_anything_opens(headers):
    client, _, connector, _ = make_client()
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(PATH, headers=headers):
            pass
    assert closed.value.code == 1008
    assert connector.connects == 0


def test_the_handshake_is_accepted_with_or_without_a_trailing_slash():
    for url in (WS_URL, WS_URL + "/"):
        client, _, connector, call = make_client()
        with client.websocket_connect(PATH, headers=sign(url)) as ws:
            open_stream(client, connector, call, ws)
        assert connector.connects == 1


@pytest.mark.parametrize("mode", ["relay", "gather"])
def test_the_stream_is_refused_in_the_other_voice_modes(mode):
    client, _, connector, _ = make_client(mode=mode)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH, headers=sign()):
            pass
    assert connector.connects == 0


# --- a call -----------------------------------------------------------------------------------


def test_audio_flows_both_ways_with_marks():
    client, _, connector, call = make_client()
    model = connector.connection
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)

        ws.send_json(media(pcm(20)))
        wait_until(lambda: model.of_type("input_audio_buffer.append"))
        assert model.of_type("input_audio_buffer.append")[0]["audio"] == pcm(20)

        model.push(created("r1"))
        model.push(audio("r1", "i1", 40))
        assert ws.receive_json() == {
            "event": "media",
            "streamSid": "MZ1",
            "media": {"payload": pcm(40)},
        }
        assert ws.receive_json() == {
            "event": "mark",
            "streamSid": "MZ1",
            "mark": {"name": "m0"},
        }
    wait_until(lambda: model.closed)  # Twilio disconnecting closes the model connection


def test_a_function_call_runs_the_tool_and_the_turn_is_stored():
    calls = []
    client, ctx, connector, call = make_client(tools=[make_lookup_tool(calls)])
    model = connector.connection
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        model.push(heard("When are you open?"))
        model.push(created("r1"))
        model.push(call_args("r1", "c1", "lookup", '{"topic": "hours"}'))
        wait_until(lambda: model.of_type("conversation.item.create"))
        model.push(done("r1"))
        wait_until(lambda: model.of_type("response.create"))
        assert model.types()[-2:] == ["conversation.item.create", "response.create"]
        assert calls == [("hours", str(call.conversation_id))]

        model.push(created("r2"))
        model.push(audio("r2", "i2"))
        model.push(words_done("r2", "Nine to five."))
        model.push(done("r2"))
        assert ws.receive_json()["event"] == "media"
        assert ws.receive_json() == {"event": "mark", "streamSid": "MZ1", "mark": {"name": "m0"}}
        ws.send_json(mark("m0"))
        wait_until(lambda: ctx.messages.rows)
    assert [(role, text) for _, role, text in ctx.messages.rows] == [
        ("user", "When are you open?"),
        ("assistant", "Nine to five."),
    ]


def test_barge_in_sends_clear_and_truncates_to_the_played_audio():
    client, _, connector, call = make_client()
    model = connector.connection
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        model.push(created("r1"))
        model.push(audio("r1", "i1", 100))
        model.push(audio("r1", "i1", 100))
        for _ in range(4):
            ws.receive_json()
        ws.send_json(mark("m0"))
        time.sleep(0.05)  # let the app read the mark before the interruption
        model.push(SPEECH_STARTED)
        assert ws.receive_json() == {"event": "clear", "streamSid": "MZ1"}
        wait_until(lambda: model.of_type("conversation.item.truncate"))
        assert model.of_type("conversation.item.truncate")[0]["audio_end_ms"] == 100


def test_an_input_guardrail_block_makes_the_model_say_the_canned_reply():
    client, ctx, connector, call = make_client()
    model = connector.connection
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        model.push(heard(INJECTION))
        wait_until(lambda: model.of_type("response.create"))
        assert (
            BLOCKED_INPUT_REPLY in model.of_type("response.create")[0]["response"]["instructions"]
        )
        wait_until(lambda: ctx.messages.rows)
    assert [(role, text) for _, role, text in ctx.messages.rows] == [
        ("user", INJECTION),
        ("assistant", BLOCKED_INPUT_REPLY),
    ]


def test_the_call_is_closed_at_the_time_limit():
    client, _, connector, call = make_client(max_call_seconds=0.3)
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert connector.connection.closed


def test_the_call_ends_when_the_model_connection_closes():
    client, _, connector, call = make_client()
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        connector.connection.push(None)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_the_caller_number_is_not_in_what_the_model_is_sent():
    client, _, connector, call = make_client(tools=[make_lookup_tool()])
    with client.websocket_connect(PATH, headers=sign()) as ws:
        open_stream(client, connector, call, ws)
        ws.send_json(media(pcm(10)))
        wait_until(lambda: connector.connection.of_type("input_audio_buffer.append"))
    assert CALLER not in str(connector.connection.sent)
