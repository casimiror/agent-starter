"""Voice, `VOICE_MODE=realtime`: Twilio Media Streams on one side, a speech-to-speech model (OpenAI
Realtime) on the other, and this session in between. The audio never touches the agent graph: the
model hears and speaks by itself, so what the graph gives the text channels (prompt, tools,
guardrails, history) is applied here around the model instead (`RealtimeVoiceService`).

No socket code: the route hands in `receive`/`send` for the Twilio WebSocket and the connector
opens the model's. Tests use plain dicts and fakes.

How a call flows:

- Twilio `start` binds the session to the conversation, opens the model connection and sends
  `session.update` (Twilio's mu-law both ways, the agent's prompt and tools).
- Caller audio (`media`) goes to `input_audio_buffer.append`; model audio
  (`response.output_audio.delta`) goes back as `media` plus a `mark` per chunk. Twilio echoes a mark
  when that chunk has *played*, which is how we know how much of a reply the caller heard.
- Barge-in (`input_audio_buffer.speech_started`): Twilio `clear` drops what is still queued, and
  `conversation.item.truncate` tells the model how much was actually played.
- The model's function calls run the agent's tools in a thread and their results go back as
  `function_call_output` + `response.create`.
- Guardrails run on the transcripts, after the audio may have started: a violation cancels the
  reply, drops the queued audio and has the model say the guardrail's canned text instead.
- A turn is stored (`messages`, one Langfuse trace) once its reply has been fully heard or cut.
"""

import asyncio
import base64
import logging
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.clients.realtime import RealtimeConnection, RealtimeConnector, RealtimeError
from app.guardrails.base import GuardrailResult
from app.services.realtime_voice_service import RealtimeVoiceService
from app.services.voice_service import VoiceCall

log = logging.getLogger("app.voice")

Receive = Callable[[], Awaitable[dict[str, Any] | None]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

# Mu-law at 8 kHz is one byte per sample: 8 bytes per millisecond of audio.
BYTES_PER_MS = 8

# Errors that mean the model session can't go on. Matched on `type`/`code` of the `error` event;
# anything else is logged and the call goes on (a failed cancel or truncate is routine). Names are
# from the API reference as summarised; an error before `session.updated` is always fatal.
FATAL_ERROR_TYPES = {"server_error", "authentication_error", "insufficient_quota"}
FATAL_ERROR_CODES = {"invalid_api_key", "insufficient_quota", "session_expired", "model_not_found"}
MAX_ERRORS = 10  # a connection that keeps failing is not worth keeping


def chunk_ms(payload: str) -> float:
    """Milliseconds of audio in one base64 mu-law chunk."""
    try:
        return len(base64.b64decode(payload)) / BYTES_PER_MS
    except ValueError:
        return 0.0


def complete_words(text: str) -> str:
    """`text` without a trailing partial word. A guardrail run on a delta must not judge `https://e`
    as if it were the whole URL."""
    return re.sub(r"\S+$", "", text)


def spoken_prefix(text: str, played_ms: float, sent_ms: float) -> str:
    """The part of a reply's transcript the caller heard, estimated from the share of its audio
    that played (the API has no per-word timing here), cut at a word boundary."""
    if sent_ms <= 0 or played_ms <= 0:
        return ""
    if played_ms >= sent_ms:
        return text
    end = int(len(text) * played_ms / sent_ms)
    head = text[:end]
    if end < len(text) and not text[end].isspace():
        head = head.rpartition(" ")[0]
    return head.strip()


def say_instructions(text: str) -> str:
    return (
        "Say exactly the following to the caller, word for word, and nothing else. "
        f"Do not add, explain or call tools: {text}"
    )


@dataclass
class _Turn:
    """What the caller said and the agent answered, until it is stored."""

    users: list[str] = field(default_factory=list)
    assistant: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    blocked_by: str | None = None
    replacement: str | None = None
    stored: bool = False


@dataclass(eq=False)  # compared by identity: responses are dict keys and set members
class _Response:
    id: str
    turn: _Turn
    item_id: str | None = None
    text: str = ""  # the reply's transcript so far
    sent_ms: float = 0.0
    played_ms: float = 0.0
    marks_out: int = 0  # chunks sent to Twilio and not yet played
    done: bool = False
    status: str = ""
    has_calls: bool = False
    cut: bool = False  # no more audio is forwarded; the caller heard only `played_ms`
    canned: bool = False  # a guardrail's replacement, already stored with the blocked turn
    settled: bool = False

    def heard(self) -> str:
        if self.cut:
            return spoken_prefix(self.text, self.played_ms, self.sent_ms)
        return self.text


class RealtimeSession:
    def __init__(
        self,
        service: RealtimeVoiceService,
        connector: RealtimeConnector,
        receive: Receive,
        send: Send,
        max_seconds: float,
    ) -> None:
        self._service = service
        self._connector = connector
        self._receive = receive
        self._send = send
        self._max_seconds = max_seconds

        self._finished = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._records: set[asyncio.Task] = set()
        self._record_lock = asyncio.Lock()  # turns are stored in order
        self._conn: RealtimeConnection | None = None
        self.call: VoiceCall | None = None
        self.call_sid = ""
        self._stream_sid = ""
        self._ready = False  # the model accepted our session.update

        self._responses: dict[str, _Response] = {}
        self._latest: _Response | None = None
        self._active_id: str | None = None  # the response being generated
        self._awaiting_created = False  # we sent response.create and no response.created yet
        self._next_canned = False
        self._pending_users: list[str] = []  # transcripts that arrived before their response
        self._continue: _Turn | None = None  # the turn a tool follow-up belongs to
        self._followup: _Turn | None = None
        self._says: deque[tuple[str, bool]] = deque()
        self._calls: set[str] = set()
        self._tools_running = 0
        self._marks: dict[str, tuple[_Response, float]] = {}
        self._seq = 0
        self._errors = 0

    # --- lifecycle ---------------------------------------------------------------------------

    async def run(self) -> None:
        """Bridge the call until either side ends, or `max_seconds` pass. Never raises."""
        self._tasks.append(asyncio.create_task(self._twilio_loop()))
        try:
            await asyncio.wait_for(self._finished.wait(), self._max_seconds)
        except TimeoutError:
            log.info("voice call reached its time limit", extra=self._fields())
        finally:
            await self._shutdown()

    def _fields(self) -> dict[str, str]:
        fields = {"call_sid": self.call_sid}
        if self.call:
            fields["visitor_id"] = str(self.call.visitor_id)
            fields["conversation_id"] = str(self.call.conversation_id)
        return fields

    def _end(self, reason: str) -> None:
        log.info("voice realtime call ending", extra={**self._fields(), "reason": reason})
        self._finished.set()

    async def _shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        # First, before anything that awaits for long: if the server cancels this handler (a
        # shutdown), the billed model session must still be closed.
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:  # already closed by the peer
                log.debug("voice realtime close failed", extra={"error": type(exc).__name__})
        await asyncio.gather(*self._tasks, return_exceptions=True)
        # Whatever was still being said was heard only as far as it played.
        for resp in list(self._responses.values()):
            if not resp.settled:
                resp.done = resp.cut = True
                await self._settle(resp, speak=False)
        if self._pending_users and self.call:
            self._spawn_record(" ".join(self._pending_users), "", None, [], "")
            self._pending_users = []
        await asyncio.gather(*list(self._records), return_exceptions=True)

    # --- Twilio ------------------------------------------------------------------------------

    async def _twilio_loop(self) -> None:
        try:
            while True:
                message = await self._receive()
                if message is None:
                    self._end("twilio closed")
                    return
                event = message.get("event")
                if event == "media":
                    await self._on_media(message)
                elif event == "mark":
                    await self._on_mark(message)
                elif event == "start":
                    await self._on_start(message)
                elif event == "stop":
                    self._end("twilio stop")
                    return
                elif event == "dtmf":
                    # Never the digit: keypad input can be an account or card number.
                    log.info("voice dtmf received", extra=self._fields())
        except Exception as exc:
            log.error("voice realtime twilio loop failed", extra={"error": type(exc).__name__})
            self._finished.set()

    async def _on_start(self, message: dict[str, Any]) -> None:
        if self._conn is not None or self.call is not None:
            return  # a second start: ignore
        start = message.get("start") or {}
        self._stream_sid = str(start.get("streamSid") or message.get("streamSid") or "")
        self.call_sid = str(start.get("callSid") or "")
        parameters = start.get("customParameters") or {}
        try:
            conversation_id = UUID(str(parameters.get("conversation_id")))
        except ValueError:
            log.warning("voice stream without a conversation id", extra=self._fields())
            self._finished.set()
            return
        # The visitor comes from the stored conversation, not from a parameter.
        call = await asyncio.to_thread(self._service.find_call, conversation_id)
        if call is None:
            log.warning("voice stream for an unknown conversation", extra=self._fields())
            self._finished.set()
            return
        self.call = call
        try:
            self._conn = await self._connector.connect()
        except RealtimeError:
            self._end("realtime connection failed")
            return
        log.info("voice realtime connected", extra=self._fields())
        if not await self._to_openai(self._service.session_update()):
            return
        self._tasks.append(asyncio.create_task(self._openai_loop()))

    async def _on_media(self, message: dict[str, Any]) -> None:
        payload = (message.get("media") or {}).get("payload")
        # Until session.updated the model would read the audio in its default format.
        if payload and self._ready:
            await self._to_openai({"type": "input_audio_buffer.append", "audio": payload})

    async def _on_mark(self, message: dict[str, Any]) -> None:
        entry = self._marks.pop(str((message.get("mark") or {}).get("name")), None)
        if entry is None:
            return  # a mark flushed by `clear`, or not ours
        resp, ms = entry
        resp.played_ms += ms
        resp.marks_out -= 1
        await self._settle(resp)

    async def _to_twilio(self, message: dict[str, Any]) -> None:
        try:
            await self._send(message)
        except Exception as exc:  # the caller hung up
            log.info("voice twilio send failed", extra={"error": type(exc).__name__})
            self._finished.set()

    async def _to_openai(self, event: dict[str, Any]) -> bool:
        if self._conn is None:
            return False
        try:
            await self._conn.send(event)
        except Exception as exc:
            log.warning("voice realtime send failed", extra={"error": type(exc).__name__})
            self._end("realtime connection lost")
            return False
        return True

    # --- the model ---------------------------------------------------------------------------

    async def _openai_loop(self) -> None:
        assert self._conn is not None
        try:
            while True:
                event = await self._conn.receive()
                if event is None:
                    self._end("realtime closed")
                    return
                try:
                    await self._on_event(event)
                except Exception as exc:  # one bad event must not end the call
                    log.error(
                        "voice realtime event failed",
                        extra={**self._fields(), "error": type(exc).__name__},
                    )
        except Exception as exc:
            log.error("voice realtime loop failed", extra={"error": type(exc).__name__})
            self._finished.set()

    async def _on_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "response.output_audio.delta":
            await self._on_audio(event)
        elif kind == "response.output_audio_transcript.delta":
            await self._on_transcript_delta(event)
        elif kind == "response.output_audio_transcript.done":
            await self._on_transcript_done(event)
        elif kind == "input_audio_buffer.speech_started":
            if self._marks:  # something is still playing: the caller talks over it
                await self._clear_playback()
        elif kind == "conversation.item.input_audio_transcription.completed":
            await self._on_user_transcript(str(event.get("transcript") or "").strip())
        elif kind == "response.function_call_arguments.done":
            self._on_call(event.get("response_id"), event)
        elif kind == "response.created":
            self._on_created(event.get("response") or {})
        elif kind == "response.done":
            await self._on_done(event.get("response") or {})
        elif kind == "response.cancelled":
            # A cancellation is reported by this event or by response.done with status
            # "cancelled"; whichever comes first closes the response, the other is ignored.
            response_id = event.get("response_id") or (event.get("response") or {}).get("id")
            await self._on_done({"id": response_id, "status": "cancelled"})
        elif kind == "session.updated":
            self._ready = True
            if self._service.greeting:
                self._says.append((self._service.greeting, False))
            await self._pump()
        elif kind == "error":
            await self._on_error(event.get("error") or {})

    async def _on_error(self, error: dict[str, Any]) -> None:
        kind, code = str(error.get("type") or ""), str(error.get("code") or "")
        # Type and code only: the message can quote what the caller said.
        log.warning(
            "voice realtime error", extra={**self._fields(), "error_type": kind, "error_code": code}
        )
        self._errors += 1
        if (
            not self._ready
            or kind in FATAL_ERROR_TYPES
            or code in FATAL_ERROR_CODES
            or self._errors > MAX_ERRORS
        ):
            self._end("realtime error")
            return
        # A response.create that failed will never get its response.created.
        self._awaiting_created = False
        await self._pump()

    # --- responses ---------------------------------------------------------------------------

    def _response(self, response_id: Any) -> _Response | None:
        return self._responses.get(str(response_id)) if response_id else None

    def _on_created(self, data: dict[str, Any]) -> None:
        response_id = str(data.get("id") or "")
        if not response_id:
            return
        self._awaiting_created = False
        if self._continue is not None:  # the follow-up to a tool call: same turn
            turn, self._continue = self._continue, None
        else:
            turn = _Turn(users=self._pending_users)
            self._pending_users = []
        resp = _Response(response_id, turn, canned=self._next_canned)
        self._next_canned = False
        self._responses[response_id] = resp
        self._latest = resp
        self._active_id = response_id

    async def _on_audio(self, event: dict[str, Any]) -> None:
        resp = self._response(event.get("response_id"))
        payload = event.get("delta")
        if resp is None or resp.cut or not payload:
            return
        resp.item_id = str(event.get("item_id") or resp.item_id or "") or None
        name = f"m{self._seq}"
        self._seq += 1
        ms = chunk_ms(payload)
        self._marks[name] = (resp, ms)
        resp.sent_ms += ms
        resp.marks_out += 1
        await self._to_twilio(
            {"event": "media", "streamSid": self._stream_sid, "media": {"payload": payload}}
        )
        await self._to_twilio(
            {"event": "mark", "streamSid": self._stream_sid, "mark": {"name": name}}
        )

    async def _on_transcript_delta(self, event: dict[str, Any]) -> None:
        resp = self._response(event.get("response_id"))
        if resp is None:
            return
        # Kept after a cut too: it is what the played share of the audio is measured against.
        resp.text += str(event.get("delta") or "")
        if not resp.canned and not resp.cut:
            await self._check_output(resp, complete_words(resp.text))

    async def _on_transcript_done(self, event: dict[str, Any]) -> None:
        resp = self._response(event.get("response_id"))
        if resp is None:
            return
        resp.text = str(event.get("transcript") or resp.text)
        if not resp.canned and not resp.cut:
            await self._check_output(resp, resp.text)

    async def _check_output(self, resp: _Response, text: str) -> None:
        if resp.turn.blocked_by:
            return
        result = self._service.check_output(text)
        if not result.allowed:
            log.warning(
                "voice reply blocked", extra={**self._fields(), "blocked_by": result.reason}
            )
            await self._block(resp, result)

    async def _on_user_transcript(self, text: str) -> None:
        if not text:
            return
        latest = self._latest
        # The reply this transcript belongs to: it usually lands while that reply is already
        # being generated or played.
        resp = latest if latest and not (latest.settled or latest.cut or latest.canned) else None
        result = self._service.check_input(text)
        if result.allowed:
            (resp.turn.users if resp else self._pending_users).append(text)
            return
        log.warning("voice input blocked", extra={**self._fields(), "blocked_by": result.reason})
        if resp is not None:
            if not resp.turn.blocked_by:
                resp.turn.users.append(text)
                await self._block(resp, result)
            return
        # Nothing of ours is being said: store the blocked turn and answer it now.
        await self._clear_playback()
        users, self._pending_users = [*self._pending_users, text], []
        self._spawn_record(" ".join(users), result.replacement or "", result.reason, [], "")
        self._says.append((result.replacement or "", True))
        await self._pump()

    async def _block(self, resp: _Response, result: GuardrailResult) -> None:
        """A guardrail refused: stop this reply and have the model say the canned text instead.
        The turn is stored with that text once the cancelled response is done."""
        resp.turn.blocked_by = result.reason
        resp.turn.replacement = result.replacement or ""
        if not resp.done:
            await self._to_openai({"type": "response.cancel"})
        await self._clear_playback(extra=resp)

    async def _clear_playback(self, extra: _Response | None = None) -> None:
        """Stop what the caller is hearing (barge-in, or a guardrail): drop Twilio's queued audio
        and tell the model how much of each reply actually played, so it forgets the rest."""
        affected = list(dict.fromkeys(resp for resp, _ in self._marks.values()))
        if extra is not None and extra not in affected:
            affected.append(extra)
        # Synchronously, before any await: the marks Twilio echoes after `clear` are not "played".
        self._marks.clear()
        for resp in affected:
            resp.marks_out = 0
            resp.cut = True
        if affected:
            await self._to_twilio({"event": "clear", "streamSid": self._stream_sid})
        for resp in affected:
            if resp.item_id and resp.sent_ms > 0:
                await self._to_openai(
                    {
                        "type": "conversation.item.truncate",
                        "item_id": resp.item_id,
                        "content_index": 0,
                        "audio_end_ms": int(resp.played_ms),
                    }
                )
        for resp in affected:
            await self._settle(resp)

    async def _on_done(self, data: dict[str, Any]) -> None:
        resp = self._response(data.get("id"))
        if resp is None or resp.done:
            return
        resp.done = True
        resp.status = str(data.get("status") or "completed")
        for item in data.get("output") or []:
            if item.get("type") == "function_call":
                self._on_call(resp.id, item)
            elif item.get("type") == "message" and not resp.item_id:
                resp.item_id = str(item.get("id") or "") or None
        if self._active_id == resp.id:
            self._active_id = None
        await self._settle(resp)
        await self._pump()

    async def _settle(self, resp: _Response, speak: bool = True) -> None:
        """Close a response once it is over *and* the caller has heard it (or it was cut): store
        the turn, or carry on if the reply was only a tool call."""
        if resp.settled or not resp.done or (resp.marks_out > 0 and not resp.cut):
            return
        resp.settled = True
        turn = resp.turn
        if resp.canned:
            return  # the blocked turn was stored with this text already
        if turn.blocked_by is not None:
            if not turn.stored:
                turn.stored = True
                self._spawn_record_turn(turn, turn.replacement or "")
                if speak:
                    self._says.append((turn.replacement or "", True))
                    await self._pump()
            return
        if heard := resp.heard():
            turn.assistant.append(heard)
        if resp.has_calls and not resp.cut and resp.status == "completed":
            return  # the turn goes on after the tools answer
        if not turn.stored:
            turn.stored = True
            self._spawn_record_turn(turn, " ".join(turn.assistant))

    # --- tools -------------------------------------------------------------------------------

    def _on_call(self, response_id: Any, data: dict[str, Any]) -> None:
        call_id = str(data.get("call_id") or "")
        resp = self._response(response_id)
        if not call_id or call_id in self._calls or resp is None:
            return
        self._calls.add(call_id)
        resp.has_calls = True
        self._tools_running += 1
        task = asyncio.create_task(
            self._run_tool(resp.turn, call_id, str(data.get("name") or ""), data.get("arguments"))
        )
        self._tasks.append(task)

    async def _run_tool(self, turn: _Turn, call_id: str, name: str, arguments: Any) -> None:
        assert self.call is not None
        try:
            output = await asyncio.to_thread(
                self._service.run_tool, name, str(arguments or ""), self.call.conversation_id
            )
        except Exception as exc:  # run_tool does not raise; this is a bug in it
            log.error("voice tool crashed", extra={"tool": name, "error": type(exc).__name__})
            output = "TOOL_ERROR: the tool failed."
        turn.tools.append(name)
        turn.results.append(f"<{name}>\n{output}")
        await self._to_openai(
            {
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": output},
            }
        )
        self._tools_running -= 1
        self._followup = turn
        await self._pump()

    # --- what we say -------------------------------------------------------------------------

    async def _pump(self) -> None:
        """Send the next `response.create`: only when no response is being generated (the API
        refuses a second) and every tool of the turn has answered."""
        if self._active_id is not None or self._awaiting_created or self._tools_running:
            return
        if self._says:
            text, canned = self._says.popleft()
            self._followup = None  # a canned reply replaces whatever would have followed
            self._next_canned = canned
            self._awaiting_created = True
            await self._to_openai(
                {
                    "type": "response.create",
                    "response": {"instructions": say_instructions(text), "tool_choice": "none"},
                }
            )
        elif self._followup is not None:
            turn, self._followup = self._followup, None
            if turn.blocked_by is not None:
                return
            self._continue = turn
            self._awaiting_created = True
            await self._to_openai({"type": "response.create"})

    # --- history -----------------------------------------------------------------------------

    def _spawn_record_turn(self, turn: _Turn, reply: str) -> None:
        self._spawn_record(
            " ".join(turn.users),
            reply,
            turn.blocked_by,
            list(turn.tools),
            "\n\n".join(turn.results),
        )

    def _spawn_record(
        self, user_text: str, reply: str, blocked_by: str | None, tools: list[str], context: str
    ) -> None:
        call = self.call
        if call is None or not (user_text or reply):
            return

        async def record() -> None:
            async with self._record_lock:
                await asyncio.to_thread(
                    self._service.record_turn, call, user_text, reply, blocked_by, tools, context
                )

        task = asyncio.create_task(record())
        self._records.add(task)
        task.add_done_callback(self._records.discard)
