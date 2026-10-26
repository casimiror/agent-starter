"""Every tool the agents can call, and what they need. `/new-tool` adds tools here."""

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.core.config import Settings
from app.domain.retrieval import Retriever


@dataclass(frozen=True, kw_only=True)
class ToolDeps:
    """What tools need (settings, repositories, clients), passed by keyword. Built in
    app/api/deps.py (`get_tool_deps`); the evaluator builds its own with in-memory stand-ins
    (app/evals/agent_run.py, `eval_tool_deps`)."""

    settings: Settings


def build_assistant_tools(deps: ToolDeps) -> list[BaseTool]:
    """The assistant's tools, each added with `/new-tool`."""
    return []


def build_retriever(deps: ToolDeps) -> Retriever | None:
    """The search behind the knowledge tool, which turns on the RAG evaluation; None while the
    project has no knowledge tool (`/new-tool`, recipe knowledge-search)."""
    return None
