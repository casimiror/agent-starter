from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from app.core.config import Settings

_client: Langfuse | None = None


def init_observability(settings: Settings) -> None:
    """Create the Langfuse client once; CallbackHandler() picks it up afterwards."""
    global _client
    if settings.langfuse_enabled and _client is None:
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_environment,
        )


@dataclass
class TurnTrace:
    """Handle for one chat turn: `config` goes to graph.invoke, `finish` records the reply."""

    config: dict[str, Any]
    _span: Any = field(default=None, repr=False)

    def finish(
        self,
        reply: str,
        blocked_by: str | None,
        tools_called: list[str] | None = None,
        context: str = "",
    ) -> None:
        """`tools_called` and `context` (the tool results) are for the online judge in Langfuse:
        an observation-level evaluator only sees this span, not the LangChain spans under it."""
        if self._span is not None:
            metadata = {"blocked_by": blocked_by, "tools_called": tools_called or []}
            self._span.update(output=reply, metadata={**metadata, "context": context})


@contextmanager
def trace_turn(
    conversation_id: str, user_id: str | None, user_text: str, tags: list[str] | None = None
) -> Generator[TurnTrace]:
    """One Langfuse trace per chat turn, grouped by conversation (session) and visitor (user).

    Follows langfuse.com/docs/observability/features/users: a root span plus
    propagate_attributes, so every LangChain observation inside inherits user and session.
    Without Langfuse configured it is a no-op.
    """
    if _client is None:
        yield TurnTrace(config={"callbacks": []})
        return
    with _client.start_as_current_observation(
        as_type="span", name="chat-turn", input=user_text
    ) as span:
        with propagate_attributes(
            user_id=user_id, session_id=conversation_id, tags=tags or [], trace_name="chat-turn"
        ):
            callbacks: list[BaseCallbackHandler] = [CallbackHandler()]
            yield TurnTrace(config={"callbacks": callbacks}, _span=span)


def flush() -> None:
    if _client:
        _client.flush()
