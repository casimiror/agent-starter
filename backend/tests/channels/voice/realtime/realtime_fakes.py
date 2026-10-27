"""Fakes for the realtime voice tests: a scripted voice model (a neutral provider, so the bridge is
proven provider-agnostic), a recording message store and a tool that notes how it was called. No
OpenAI, no Twilio, no LLM."""

import asyncio
import queue
import time
from types import SimpleNamespace
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.assistant_agent import ASSISTANT_PROMPT, assistant_guardrails
from app.agents.builder import load_prompt
from app.clients.voice_models.base import MULAW_8K, AudioFormat, ModelEvent, VoiceModelError
from app.services.channels.voice.realtime.service import RealtimeVoiceService
from app.tools.builder import ToolBuilder
from tests.channels.voice.voice_fakes import make_settings, make_voice


class FakeRealtime:
    """The model side. The test pushes neutral events; the bridge's commands are recorded as dicts
    with a `type` (the command's name) and its arguments.

    Thread-safe on purpose: the Starlette TestClient runs the app in another thread."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False
        self._incoming: queue.Queue = queue.Queue()

    def push(self, event: ModelEvent | None) -> None:
        """A model event; None closes the connection from the model's side."""
        self._incoming.put(event)

    def _record(self, kind: str, **fields: Any) -> None:
        if self.closed:
            raise RuntimeError("closed")
        self.sent.append({"type": kind, **fields})

    async def configure(self, spec) -> None:
        self._record("configure", spec=spec)

    async def append_audio(self, audio: str) -> None:
        self._record("append_audio", audio=audio)

    async def respond(self) -> None:
        self._record("respond")

    async def say(self, text: str) -> None:
        self._record("say", text=text)

    async def cancel(self) -> None:
        self._record("cancel")

    async def truncate(self, item_id: str, audio_end_ms: int) -> None:
        self._record("truncate", item_id=item_id, audio_end_ms=audio_end_ms)

    async def tool_result(self, call_id: str, output: str) -> None:
        self._record("tool_result", call_id=call_id, output=output)

    async def receive(self) -> ModelEvent | None:
        while True:
            try:
                return self._incoming.get_nowait()
            except queue.Empty:
                if self.closed:
                    return None
                await asyncio.sleep(0.002)

    async def close(self) -> None:
        self.closed = True

    def types(self) -> list[str]:
        return [event["type"] for event in self.sent]

    def of_type(self, kind: str) -> list[dict]:
        return [event for event in self.sent if event["type"] == kind]


class FakeVoiceModel:
    """A `VoiceModelProvider` that hands out one scripted connection."""

    def __init__(
        self,
        fail: bool = False,
        audio_format: AudioFormat = MULAW_8K,
        name: str = "fake",
        model: str = "fake-realtime",
    ) -> None:
        self.connection = FakeRealtime()
        self.fail = fail
        self.connects = 0
        self.audio_format = audio_format
        self.name = name
        self.model = model

    async def connect(self) -> FakeRealtime:
        self.connects += 1
        if self.fail:
            raise VoiceModelError("down", kind="TimeoutError")
        return self.connection


class FakeMessages:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[tuple] = []
        self.fail = fail

    def append(self, conversation_id, role, content):
        if self.fail:
            raise RuntimeError("database down")
        self.rows.append((conversation_id, role, content))


class LookupArgs(BaseModel):
    topic: str = Field(description="What to look up")


def make_lookup_tool(calls: list | None = None, result: str = "INFO: open 9 to 5"):
    calls = [] if calls is None else calls

    def lookup(topic: str, config: RunnableConfig) -> str:
        calls.append((topic, config["configurable"]["conversation_id"]))
        return result

    return (
        ToolBuilder("lookup")
        .describe("Look up opening hours. Use when the caller asks when we are open.")
        .args(LookupArgs)
        .handler(lookup)
        .build()
    )


def make_realtime_service(tools=None, messages=None, extra_output=(), **settings_values):
    settings_values.setdefault("voice_mode", "realtime")
    settings = make_settings(openai_api_key="sk-test", **settings_values)
    voice = make_voice()
    messages = messages or FakeMessages()
    flushed: list[int] = []
    inputs, outputs = assistant_guardrails(settings)
    service = RealtimeVoiceService(
        voice.service,
        messages,
        [] if tools is None else tools,
        load_prompt(ASSISTANT_PROMPT),
        inputs,
        [*outputs, *extra_output],
        model=settings.voice_realtime_model,
        greeting=settings.voice_greeting,
        flush=lambda: flushed.append(1),
    )
    # Every call to record_turn: (call, user_text, reply, blocked_by, tools_called, context).
    records: list[tuple] = []
    original = service.record_turn

    def spy(*args):
        records.append(args)
        original(*args)

    service.record_turn = spy
    return SimpleNamespace(
        service=service,
        voice=voice,
        messages=messages,
        flushed=flushed,
        settings=settings,
        records=records,
    )


def wait_until(condition, timeout: float = 3.0) -> None:
    """Poll from the test thread until `condition()` holds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for the condition")
