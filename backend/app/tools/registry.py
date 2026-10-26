"""Every tool the agents can call, and what they need. `/new-tool` adds tools here."""

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.core.config import Settings
from app.domain.retrieval import Retriever


@dataclass(frozen=True)
class ToolDeps:
    """What tools need (settings, repositories, clients). Built in app/api/deps.py; the evaluator
    builds its own with in-memory repositories (app/evals/agent_run.py)."""

    settings: Settings


def build_assistant_tools(deps: ToolDeps) -> list[BaseTool]:
    """The assistant's tools. Empty until the project adds its own (`/new-tool`)."""
    return []


def build_retriever(deps: ToolDeps) -> Retriever | None:
    """The search behind the knowledge tool, for the RAG evaluation. None until the project adds
    a knowledge-search tool (`/new-tool`, recipe knowledge-search)."""
    return None
