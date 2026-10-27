"""What a realtime voice call needs from the rest of the app, with no socket code.

In `relay` and `gather` the agent graph answers every turn. In `realtime` the speech-to-speech
model answers by itself, so this service gives it the same three things the graph has, taken from
the same definitions: the prompt (as the session's instructions), the tools (as neutral function
specs) and the guardrails (run on transcripts). The model itself (which provider, voice, audio) is
a `VoiceModelProvider`, built apart from the agent. It also stores each finished turn in
`messages`, as `ChatService` does, and traces it in Langfuse.

Blocking (database, tools, Langfuse): the session calls it from threads.
"""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import ValidationError

from app.clients.voice_models.base import ToolSpec, VoiceSessionSpec
from app.core import observability
from app.core.observability import trace_turn
from app.guardrails.base import Guardrail, GuardrailResult, run_guardrails
from app.repositories.conversation_repository import ConversationRepository
from app.services.channels.voice.service import VoiceCall, VoiceService

log = logging.getLogger("app.voice")


def tool_specs(tools: Sequence[BaseTool]) -> tuple[ToolSpec, ...]:
    """The agent's LangChain tools as neutral function specs: same name, description and JSON
    schema of the arguments the model sees in the text channels."""
    specs = []
    for tool in tools:
        schema = tool.args_schema
        if schema is None:
            parameters: dict[str, Any] = {"type": "object", "properties": {}}
        elif isinstance(schema, dict):
            parameters = schema
        else:
            parameters = schema.model_json_schema()
        specs.append(ToolSpec(tool.name, tool.description, parameters))
    return tuple(specs)


class RealtimeVoiceService:
    def __init__(
        self,
        voice: VoiceService,
        conversations: ConversationRepository,
        tools: Sequence[BaseTool],
        instructions: str,
        input_guardrails: list[Guardrail],
        output_guardrails: list[Guardrail],
        model: str,
        greeting: str,
        flush: Callable[[], None] = observability.flush,
    ) -> None:
        self._voice = voice
        self._conversations = conversations
        self._tools = {tool.name: tool for tool in tools}
        self._spec = VoiceSessionSpec(instructions, tool_specs(tools))
        self._input_guardrails = input_guardrails
        self._output_guardrails = output_guardrails
        self._model = model
        self.greeting = greeting
        self._flush = flush

    def find_call(self, conversation_id: UUID) -> VoiceCall | None:
        """The voice call a conversation id (a Stream parameter) belongs to, else None."""
        return self._voice.find_call(conversation_id)

    def session_spec(self) -> VoiceSessionSpec:
        """The agent as the voice model is configured with it: the text agent's prompt and tools.
        How the provider turns it into its own session setup is the provider's business."""
        return self._spec

    def check_input(self, text: str) -> GuardrailResult:
        return run_guardrails(self._input_guardrails, text)

    def check_output(self, text: str) -> GuardrailResult:
        return run_guardrails(self._output_guardrails, text)

    def run_tool(self, name: str, arguments: str, conversation_id: UUID) -> str:
        """Run one tool the model asked for and return its result as the string the model reads.
        Never raises: a missing tool, unreadable arguments or a failing tool are an UPPERCASE-coded
        message the model can react to (docs/conventions.md). Arguments are never logged."""
        tool = self._tools.get(name)
        if tool is None:
            log.warning("voice realtime asked for an unknown tool", extra={"tool": name[:64]})
            return "UNKNOWN_TOOL: there is no tool with that name."
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            return "BAD_ARGUMENTS: the arguments are not valid JSON."
        if not isinstance(args, dict):
            return "BAD_ARGUMENTS: the arguments must be a JSON object."
        try:
            # The same per-turn context the graph gives its tools (ToolBuilder's `config`).
            result = tool.invoke(
                args, config={"configurable": {"conversation_id": str(conversation_id)}}
            )
        except ValidationError:
            return "BAD_ARGUMENTS: the arguments do not match the tool's schema."
        except Exception as exc:
            log.error("voice tool failed", extra={"tool": name, "error": type(exc).__name__})
            return "TOOL_ERROR: the tool failed."
        return result if isinstance(result, str) else json.dumps(result, default=str)

    def record_turn(
        self,
        call: VoiceCall,
        user_text: str,
        reply: str,
        blocked_by: str | None,
        tools_called: list[str],
        context: str = "",
    ) -> None:
        """Store a finished turn (what the caller said, what they heard) and trace it. Never
        raises: a failed write must not end the call. Empty text is not stored (the greeting has
        no caller text)."""
        fields = {
            "visitor_id": str(call.visitor_id),
            "conversation_id": str(call.conversation_id),
        }
        try:
            tags = ["channel:voice"]
            with trace_turn(
                str(call.conversation_id), str(call.visitor_id), user_text, tags
            ) as trace:
                trace.finish(reply, blocked_by, tools_called, context, self._model)
            if user_text:
                self._conversations.append(call.conversation_id, "user", user_text)
            if reply:
                self._conversations.append(call.conversation_id, "assistant", reply)
            # Never the words: they can hold personal data.
            log.info(
                "voice realtime turn",
                extra={
                    **fields,
                    "channel": "voice",
                    "tools_called": tools_called,
                    "blocked_by": blocked_by,
                    "model": self._model,
                },
            )
        except Exception as exc:
            # Only the type: a database error can print the statement's parameters.
            log.error(
                "voice realtime turn not stored", extra={**fields, "error": type(exc).__name__}
            )
        finally:
            self._flush()
