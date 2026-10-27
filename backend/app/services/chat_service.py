import logging
import time
from dataclasses import dataclass
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from app.core.observability import trace_turn
from app.domain.models import Channel, Message
from app.repositories.conversation_repository import ConversationRepository

log = logging.getLogger("app.chat")


@dataclass(frozen=True)
class TurnResult:
    conversation_id: UUID
    message_id: UUID  # the stored assistant message, the target of 👍/👎 feedback
    reply: str
    blocked_by: str | None


def _to_langchain(history: list[Message]) -> list[BaseMessage]:
    return [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in history]


def _tool_activity(turn: list[BaseMessage]) -> tuple[list[str], str]:
    """Tools the agent called this turn and what they returned, for the online judge."""
    called = [call["name"] for m in turn if isinstance(m, AIMessage) for call in m.tool_calls]
    results = [f"<{m.name}>\n{m.text}" for m in turn if isinstance(m, ToolMessage)]
    return called, "\n\n".join(results)


def _model_used(turn: list[BaseMessage]) -> str | None:
    """The model that wrote the last LLM reply: shows when a fallback answered. None when no LLM
    ran (an input guardrail blocked the turn)."""
    for message in reversed(turn):
        if isinstance(message, AIMessage) and message.response_metadata:
            meta = message.response_metadata
            return meta.get("model_name") or meta.get("model")
    return None


class ChatService:
    def __init__(
        self,
        conversations: ConversationRepository,
        agent: CompiledStateGraph,
        history_limit: int,
        primary_model: str | None = None,
    ) -> None:
        self._conversations = conversations
        self._agent = agent
        self._history_limit = history_limit
        self._primary_model = primary_model  # a reply from any other model came from a fallback

    def handle_turn(
        self,
        conversation_id: UUID | None,
        user_text: str,
        visitor_id: UUID | None = None,
        channel: Channel = "web",
    ) -> TurnResult:
        # The channel is stored and traced only: the agent and its prompt never see it.
        conversation = self._conversations.get_or_create(conversation_id, visitor_id, channel)
        history = self._conversations.recent_messages(conversation.id, self._history_limit)

        # The stored visitor wins, so one conversation is never split across Langfuse users.
        visitor = conversation.visitor_id or visitor_id
        user_id = str(visitor) if visitor else None
        started = time.perf_counter()
        # An existing conversation keeps its own channel, so tag with the stored one.
        tags = [f"channel:{conversation.channel}"]
        with trace_turn(str(conversation.id), user_id, user_text, tags) as trace:
            config = {**trace.config, "configurable": {"conversation_id": str(conversation.id)}}
            messages = [*_to_langchain(history), HumanMessage(user_text)]
            state = self._agent.invoke({"messages": messages}, config)
            reply = state["messages"][-1].text
            turn = state["messages"][len(messages) :]
            tools_called, context = _tool_activity(turn)
            model = _model_used(turn)
            trace.finish(reply, state.get("blocked_by"), tools_called, context, model)

        # Persist only after a successful turn so a failed LLM call leaves no half-turn.
        self._conversations.append(conversation.id, "user", user_text)
        answer = self._conversations.append(conversation.id, "assistant", reply)
        # Providers may append a version to the name (claude-x -> claude-x-20261001).
        fallback = bool(model and self._primary_model and not model.startswith(self._primary_model))
        # Never the user's text or the reply here: they can hold personal data.
        log.log(
            logging.WARNING if fallback else logging.INFO,
            "chat turn",
            extra={
                "conversation_id": str(conversation.id),
                "channel": conversation.channel,
                "history_messages": len(history),
                "tools_called": tools_called,
                "blocked_by": state.get("blocked_by"),
                "model": model,
                "fallback": fallback,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return TurnResult(conversation.id, answer.id, reply, state.get("blocked_by"))
