import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DATASET_FILE = Path(__file__).resolve().parent / "dataset.jsonl"

Category = Literal[
    # Retrieval/answer categories (same as the RAG course evaluator)
    "direct_fact",
    "temporal",
    "spanning",
    "comparative",
    "numerical",
    "relationship",
    "holistic",
    # Assistant behaviour
    "guardrail",
    "off_topic",
    "multi_question",
    "escalation",
    "action",
]
Behavior = Literal["answer", "block", "decline", "escalate", "act", "clarify"]


class EvalCase(BaseModel):
    """One test question for the assistant agent. /kickoff writes the dataset from plan.md."""

    id: str
    category: Category
    scenario: int | None = Field(None, ge=1, description="plan.md scenario it covers")
    language: str = Field("en", description="ISO 639-1 code of the question's language")
    question: str
    keywords: list[str] = Field(
        description="Must appear in the retrieved knowledge (MRR, nDCG, coverage)"
    )
    expected_sources: list[str] = Field(description="Knowledge documents that hold the answer")
    reference_answer: str = Field(description="What a good reply says or does, for the judge")
    expected_behavior: Behavior
    expected_tools: list[str] = Field(description="Tools the agent must call")
    forbidden_tools: list[str] = Field(
        default=[], description="Tools the agent must not call, e.g. before it has every detail"
    )
    forbidden: list[str] = Field(description="Substrings that must not appear in the reply")


def load_dataset(path: Path = DATASET_FILE) -> list[EvalCase]:
    with path.open(encoding="utf-8") as f:
        return [EvalCase.model_validate(json.loads(line)) for line in f if line.strip()]
