"""LLM-as-a-judge, extended from the RAG course: accuracy, completeness and relevance, plus
groundedness and behaviour for an assistant that answers from its tools."""

from functools import cache
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.evals.agent_run import AgentRun
from app.evals.dataset import EvalCase

_PROMPT = Path(__file__).resolve().parent / "prompts" / "judge.md"
_SCORE = {"ge": 1, "le": 5}


class AnswerEval(BaseModel):
    feedback: str = Field(description="Two or three sentences on what is right or wrong")
    accuracy: int = Field(description="1-5, see rubric", **_SCORE)
    completeness: int = Field(description="1-5, see rubric", **_SCORE)
    relevance: int = Field(description="1-5, see rubric", **_SCORE)
    groundedness: int = Field(description="1-5, see rubric", **_SCORE)
    behavior: int = Field(description="1-5, see rubric", **_SCORE)

    @property
    def scores(self) -> dict[str, int]:
        return self.model_dump(exclude={"feedback"})


@cache
def _rubric() -> str:
    return _PROMPT.read_text()


def _context(run: AgentRun) -> str:
    if not run.retrieved:
        return "(nothing retrieved)"
    return "\n\n".join(f"[{d.source} › {d.title}]\n{d.text}" for d in run.retrieved)


def judge_answer(judge: BaseChatModel, case: EvalCase, run: AgentRun) -> AnswerEval:
    task = f"""Question:
{case.question}

Expected behaviour: {case.expected_behavior}

Reference answer:
{case.reference_answer}

Retrieved context the bot saw:
{_context(run)}

Tools the bot called: {", ".join(run.tools_called) or "none"}
Guardrail that replaced the reply: {run.blocked_by or "none"}

Bot reply:
{run.reply}"""
    structured = judge.with_structured_output(AnswerEval, method="function_calling")
    return structured.invoke([SystemMessage(_rubric()), HumanMessage(task)])
