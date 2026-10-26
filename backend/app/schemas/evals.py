from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class StartEvalRequest(BaseModel):
    kind: Literal["retrieval", "answer"]
    categories: list[str] | None = None


class EvalJobResponse(BaseModel):
    id: str
    kind: Literal["retrieval", "answer"]
    status: Literal["running", "done", "failed"]
    done: int
    total: int
    run_id: str | None
    error: str | None


class EvalRunItem(BaseModel):
    """A run in the list: its summary without the per-case results."""

    id: str
    kind: Literal["retrieval", "answer"]
    started_at: datetime
    finished_at: datetime
    summary: dict[str, Any]
    langfuse_url: str | None


class EvalCapabilities(BaseModel):
    retrieval: bool  # a knowledge tool exists, so the RAG evaluation can run
