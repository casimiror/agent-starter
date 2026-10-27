"""OpenAI Realtime as a voice model provider: the socket against a local server, the translation of
its events into neutral ones and of neutral commands into its JSON. No OpenAI involved."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from app.clients.voice_models.base import (
    MULAW_8K,
    AssistantTranscriptDelta,
    AssistantTranscriptDone,
    AudioChunk,
    CallerSpeaking,
    ModelError,
    ResponseDone,
    ResponseStarted,
    SessionReady,
    ToolCall,
    ToolSpec,
    TurnDetection,
    UserTranscript,
    UserTranscriptFailed,
    UserTurnEnded,
    VoiceModelConfig,
    VoiceModelError,
    VoiceSessionSpec,
)
from app.clients.voice_models.openai import (
    OpenAIRealtimeProvider,
    _OpenAIConnection,
    session_update,
    translate,
)

CONFIG = VoiceModelConfig(
    model="gpt-realtime-2.1",
    api_key="sk-test",
    voice="marin",
    transcription_model="gpt-4o-mini-transcribe",
)


def provider(url: str | None = None, **values) -> OpenAIRealtimeProvider:
    fields = {**vars(CONFIG), **values}
    if url:
        fields["endpoint"] = url
    return OpenAIRealtimeProvider(VoiceModelConfig(**fields))


# --- the socket -------------------------------------------------------------------------------


def run_against_local_server(scenario):
    """Run `scenario(url, seen)` against a local WebSocket server: no OpenAI involved."""
    seen: dict = {}

    async def handler(socket):
        seen["path"] = socket.request.path
        seen["authorization"] = socket.request.headers.get("Authorization")
        seen["beta"] = socket.request.headers.get("OpenAI-Beta")
        seen["safety"] = socket.request.headers.get("OpenAI-Safety-Identifier")
        async for raw in socket:
            await socket.send(raw)  # echo as the "server event"
            if raw == '{"type": "stop"}':
                await socket.close()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            await scenario(f"ws://127.0.0.1:{port}/v1/realtime", seen)

    asyncio.run(main())


def test_it_connects_and_speaks_neutral_commands_and_events():
    async def scenario(url, seen):
        connection = await provider(url).connect()
        await connection.cancel()  # the echo of {"type": "response.cancel"} is not an event we use
        await connection.append_audio("AAAA")
        # The server echoes our own commands: translate() maps none of them, so the next neutral
        # event is the one we make it echo below.
        await connection._socket.send(json.dumps({"type": "session.updated"}))
        assert await connection.receive() == SessionReady()
        await connection.close()

    run_against_local_server(scenario)


def test_the_handshake_has_the_model_in_the_url_and_a_bearer_key_only():
    captured = {}

    async def scenario(url, seen):
        connection = await provider(url).connect()
        await connection.respond()
        await connection.close()
        await asyncio.sleep(0.05)
        captured.update(seen)

    run_against_local_server(scenario)
    assert captured["path"] == "/v1/realtime?model=gpt-realtime-2.1"
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["beta"] is None
    assert captured["safety"] is None


def test_receive_returns_none_once_the_server_closes():
    async def scenario(url, seen):
        connection = await provider(url).connect()
        await connection._socket.send('{"type": "stop"}')
        assert await connection.receive() is None
        await connection.close()

    run_against_local_server(scenario)


def test_unreadable_and_unknown_server_events_are_skipped():
    async def scenario(url, seen):
        connection = await provider(url).connect()
        for raw in ("not json", "[1]", '{"type": "rate_limits.updated"}', '{"type": "stop"}'):
            await connection._socket.send(raw)
        assert await connection.receive() is None
        await connection.close()

    run_against_local_server(scenario)


def test_a_failed_connection_raises_without_the_key(caplog):
    async def main():
        # Nothing listens on port 1.
        await provider("ws://127.0.0.1:1/v1/realtime", api_key="sk-secret").connect()

    with pytest.raises(VoiceModelError) as error:
        asyncio.run(main())
    assert "sk-secret" not in str(error.value)
    assert "sk-secret" not in caplog.text
    assert caplog.records[-1].provider == "openai"


def test_it_declares_what_the_builder_and_the_bridge_need():
    assert OpenAIRealtimeProvider.name == "openai"
    assert OpenAIRealtimeProvider.audio_format == MULAW_8K
    assert OpenAIRealtimeProvider.api_key_setting == "openai_api_key"
    assert provider().model == "gpt-realtime-2.1"


# --- neutral commands -> OpenAI JSON ----------------------------------------------------------


class RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def commands(run):
    socket = RecordingSocket()
    asyncio.run(run(_OpenAIConnection(socket, CONFIG)))
    return socket.sent


def test_commands_are_the_exact_json_openai_has_always_been_sent():
    """No behavior change: these payloads are the ones the bridge sent before providers existed."""

    async def run(conn):
        await conn.append_audio("QUJD")
        await conn.respond()
        await conn.say("Hello there")
        await conn.cancel()
        await conn.truncate("item_1", 1234)
        await conn.tool_result("call_1", "INFO: open 9 to 5")

    assert commands(run) == [
        {"type": "input_audio_buffer.append", "audio": "QUJD"},
        {"type": "response.create"},
        {
            "type": "response.create",
            "response": {
                "instructions": (
                    "Say exactly the following to the caller, word for word, and nothing else. "
                    "Do not add, explain or call tools: Hello there"
                ),
                "tool_choice": "none",
            },
        },
        {"type": "response.cancel"},
        {
            "type": "conversation.item.truncate",
            "item_id": "item_1",
            "content_index": 0,
            "audio_end_ms": 1234,
        },
        {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "INFO: open 9 to 5",
            },
        },
    ]


def test_configure_sends_the_exact_session_update_of_before():
    spec = VoiceSessionSpec(
        "Be brief.",
        (
            ToolSpec(
                "lookup",
                "Look up hours.",
                {"type": "object", "properties": {"topic": {"type": "string"}}},
            ),
        ),
    )

    async def run(conn):
        await conn.configure(spec)

    assert commands(run) == [
        {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},
                        "turn_detection": {
                            "type": "server_vad",
                            "create_response": False,
                            "interrupt_response": True,
                        },
                        "transcription": {"model": "gpt-4o-mini-transcribe"},
                    },
                    "output": {"format": {"type": "audio/pcmu"}, "voice": "marin"},
                },
                "instructions": "Be brief.",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "description": "Look up hours.",
                        "parameters": {
                            "type": "object",
                            "properties": {"topic": {"type": "string"}},
                        },
                    }
                ],
                "tool_choice": "auto",
            },
        }
    ]


def test_the_session_follows_the_configured_voice_transcription_and_turn_detection():
    config = VoiceModelConfig(
        voice="cedar",
        transcription_model="whisper-1",
        turn_detection=TurnDetection(create_response=True, interrupt_response=False),
        language="es-ES",
    )
    session = session_update(config, VoiceSessionSpec("x"))["session"]
    assert session["audio"]["output"]["voice"] == "cedar"
    assert session["audio"]["input"]["transcription"] == {"model": "whisper-1"}
    assert session["audio"]["input"]["turn_detection"] == {
        "type": "server_vad",
        "create_response": True,
        "interrupt_response": False,
    }
    assert session["tools"] == []
    assert "es-ES" not in str(session)  # the language is not sent: nothing changed with OpenAI


# --- OpenAI events -> neutral events ----------------------------------------------------------


def test_audio_and_transcripts():
    delta = {"type": "response.output_audio.delta", "response_id": "r1", "item_id": "i1"}
    assert translate({**delta, "delta": "QQ=="}) == AudioChunk("r1", "i1", "QQ==")
    assert translate(
        {"type": "response.output_audio_transcript.delta", "response_id": "r1", "delta": "Hi "}
    ) == AssistantTranscriptDelta("r1", "Hi ")
    assert translate(
        {"type": "response.output_audio_transcript.done", "response_id": "r1", "transcript": "Hi."}
    ) == AssistantTranscriptDone("r1", "Hi.")


def test_the_callers_turn():
    assert translate({"type": "input_audio_buffer.speech_started"}) == CallerSpeaking()
    for kind in ("input_audio_buffer.committed", "input_audio_buffer.speech_stopped"):
        assert translate({"type": kind, "item_id": "u1"}) == UserTurnEnded("u1")
    assert translate(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1",
            "transcript": "  hello \n",
        }
    ) == UserTranscript("u1", "hello")
    assert translate(
        {"type": "conversation.item.input_audio_transcription.failed", "item_id": "u1"}
    ) == UserTranscriptFailed("u1")


def test_responses_and_tool_calls():
    assert translate({"type": "session.updated"}) == SessionReady()
    assert translate({"type": "response.created", "response": {"id": "r1"}}) == ResponseStarted(
        "r1"
    )
    assert translate({"type": "response.created", "response": {}}) is None
    call = ToolCall("r1", "c1", "lookup", '{"topic": "hours"}')
    assert (
        translate(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "r1",
                "call_id": "c1",
                "name": "lookup",
                "arguments": '{"topic": "hours"}',
            }
        )
        == call
    )
    done = translate(
        {
            "type": "response.done",
            "response": {
                "id": "r1",
                "status": "completed",
                "output": [
                    {"type": "message", "id": "m1"},
                    {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
                ],
            },
        }
    )
    assert done == ResponseDone("r1", "completed", "m1", (ToolCall("r1", "c1", "lookup", "{}"),))
    assert translate({"type": "response.done", "response": {"id": "r2"}}) == ResponseDone(
        "r2", "completed"
    )


def test_a_cancellation_is_a_done_with_status_cancelled_whichever_event_reports_it():
    expected = ResponseDone("r1", "cancelled")
    assert translate({"type": "response.cancelled", "response_id": "r1"}) == expected
    assert translate({"type": "response.cancelled", "response": {"id": "r1"}}) == expected


def test_errors_are_classified_here_not_in_the_bridge():
    fatal_type = translate({"type": "error", "error": {"type": "server_error", "code": "boom"}})
    assert fatal_type == ModelError("server_error", "boom", fatal=True)
    fatal_code = translate({"type": "error", "error": {"type": "x", "code": "invalid_api_key"}})
    assert fatal_code.fatal
    routine = translate({"type": "error", "error": {"type": "invalid_request_error", "code": "x"}})
    assert routine == ModelError("invalid_request_error", "x")
    active = translate(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "conversation_already_has_active_response",
                "message": "what the caller said",
            },
        }
    )
    assert active.active_response and not active.fatal
    assert "what the caller said" not in str(active)


def test_an_event_the_bridge_does_not_use_is_none():
    assert translate({"type": "rate_limits.updated"}) is None
    assert translate({}) is None
