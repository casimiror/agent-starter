import asyncio

import pytest
from websockets.asyncio.server import serve

from app.clients.realtime import OpenAIRealtimeConnector, RealtimeError


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


def test_it_connects_with_the_model_in_the_url_and_a_bearer_key_only():
    async def scenario(url, seen):
        connection = await OpenAIRealtimeConnector("sk-test", "gpt-realtime-2.1", url).connect()
        await connection.send({"type": "ping", "n": 1})
        assert await connection.receive() == {"type": "ping", "n": 1}
        await connection.close()

    run_against_local_server(scenario)


def test_the_handshake_carries_no_beta_or_identity_header():
    captured = {}

    async def scenario(url, seen):
        connection = await OpenAIRealtimeConnector("sk-test", "gpt-realtime-2.1", url).connect()
        await connection.send({"type": "ping"})
        await connection.receive()
        await connection.close()
        captured.update(seen)

    run_against_local_server(scenario)
    assert captured["path"] == "/v1/realtime?model=gpt-realtime-2.1"
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["beta"] is None
    assert captured["safety"] is None


def test_receive_returns_none_once_the_server_closes():
    async def scenario(url, seen):
        connection = await OpenAIRealtimeConnector("k", "m", url).connect()
        await connection.send({"type": "stop"})
        assert await connection.receive() == {"type": "stop"}
        assert await connection.receive() is None
        await connection.close()

    run_against_local_server(scenario)


def test_a_failed_connection_raises_without_the_key(caplog):
    async def main():
        # Nothing listens on port 1.
        await OpenAIRealtimeConnector("sk-secret", "m", "ws://127.0.0.1:1/v1/realtime").connect()

    with pytest.raises(RealtimeError) as error:
        asyncio.run(main())
    assert "sk-secret" not in str(error.value)
    assert "sk-secret" not in caplog.text
