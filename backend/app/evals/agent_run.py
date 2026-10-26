"""Run the real assistant agent on one question and record what it did.

Same graph as production (`build_assistant_agent`: prompt, tools, guardrails, model), but tools
that write to the database get in-memory repositories (see `eval_tool_deps`), so an evaluation
never touches Postgres.
"""

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.agents.assistant_agent import build_assistant_agent
from app.core.config import Settings
from app.core.llm import build_chat_models
from app.domain.retrieval import KNOWLEDGE_TOOL, RetrievedDoc, parse_docs
from app.tools.registry import ToolDeps, build_assistant_tools


class RecordingRepository:
    """Stands in for a repository a tool writes to: keeps what it would have stored."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create(self, conversation_id: Any, **fields: Any) -> None:
        self.created.append({"conversation_id": str(conversation_id), **fields})


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]


@dataclass
class AgentRun:
    reply: str
    blocked_by: str | None
    tool_calls: list[ToolCall]
    retrieved: list[RetrievedDoc]  # what the knowledge tool returned, in call order
    latency_s: float
    error: str | None = None
    tools_called: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.tools_called = [call.name for call in self.tool_calls]


def eval_tool_deps(settings: Settings) -> ToolDeps:
    """The tools' dependencies for evaluations: a tool that writes gets a RecordingRepository
    here instead of its Postgres repository."""
    return ToolDeps(settings)


def build_eval_agent(settings: Settings) -> CompiledStateGraph:
    tools = build_assistant_tools(eval_tool_deps(settings))
    return build_assistant_agent(build_chat_models(settings), tools, settings)


def run_agent(
    agent: CompiledStateGraph, question: str, callbacks: list[BaseCallbackHandler]
) -> AgentRun:
    config = {
        "callbacks": callbacks,
        "configurable": {"conversation_id": str(uuid4())},
        "metadata": {"langfuse_tags": ["eval"]},
    }
    started = time.perf_counter()
    try:
        state = agent.invoke({"messages": [HumanMessage(question)]}, config)
    except Exception as exc:  # noqa: BLE001 - one failing case must not stop the run
        return AgentRun("", None, [], [], time.perf_counter() - started, error=repr(exc))

    tool_calls, retrieved = [], []
    for message in state["messages"]:
        if isinstance(message, AIMessage):
            tool_calls += [ToolCall(name=c["name"], args=c["args"]) for c in message.tool_calls]
        elif isinstance(message, ToolMessage) and message.name == KNOWLEDGE_TOOL:
            retrieved += parse_docs(message.text)
    return AgentRun(
        reply=state["messages"][-1].text,
        blocked_by=state.get("blocked_by"),
        tool_calls=tool_calls,
        retrieved=retrieved,
        latency_s=time.perf_counter() - started,
    )
