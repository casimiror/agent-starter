"""What one evaluation run produces. Serialized as one JSON file per run."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from statistics import mean
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field

from app.evals.agent_run import ToolCall
from app.evals.checks import Check
from app.evals.dataset import EvalCase
from app.evals.judge import AnswerEval
from app.evals.retrieval import RetrievalMetrics

# A case passes when every deterministic check passes and the judge gives at least this
# accuracy and behaviour (1-5). Same "acceptable" bar as the course's amber threshold.
PASS_SCORE = 4


class RetrievalCaseResult(BaseModel):
    """RAG evaluation: the knowledge-base tool's search on the question, no LLM."""

    case: EvalCase
    retrieval: RetrievalMetrics


class CaseResult(BaseModel):
    """LLM evaluation: the real agent answers and the judge scores the reply."""

    case: EvalCase
    reply: str
    blocked_by: str | None
    tool_calls: list[ToolCall]
    agent_retrieval: RetrievalMetrics | None  # what the agent's own searches returned
    checks: list[Check]
    judge: AnswerEval | None
    judge_error: str | None = None
    latency_s: float
    trace_id: str | None = None

    @computed_field  # serialized, so the /eval page and the JSON show it
    @property
    def passed(self) -> bool:
        checks_ok = all(c.passed for c in self.checks)
        judge_ok = self.judge is not None and min(self.judge.accuracy, self.judge.behavior) >= (
            PASS_SCORE
        )
        return checks_ok and judge_ok


class RetrievalSummary(BaseModel):
    cases: int
    mrr: float
    ndcg: float
    keyword_coverage: float  # 0..1
    source_hit: float  # share of cases where an expected source was retrieved


class AnswerSummary(BaseModel):
    cases: int
    pass_rate: float
    checks_pass_rate: float
    judge: dict[str, float]  # mean of each 1-5 score
    agent_retrieval: dict[str, float]  # mrr, ndcg, keyword_coverage, source_hit
    latency_s: float


class _Run(BaseModel):
    id: str
    started_at: datetime
    finished_at: datetime
    langfuse_url: str | None = None


class RetrievalRun(_Run):
    kind: Literal["retrieval"] = "retrieval"
    summary: RetrievalSummary
    by_category: dict[str, RetrievalSummary]
    results: list[RetrievalCaseResult]


class AnswerRun(_Run):
    kind: Literal["answer"] = "answer"
    bot_model: str
    judge_model: str
    summary: AnswerSummary
    by_category: dict[str, AnswerSummary]
    results: list[CaseResult]


EvalRun = Annotated[RetrievalRun | AnswerRun, Field(discriminator="kind")]


def _retrieval_means(metrics: list[RetrievalMetrics | None]) -> dict[str, float]:
    present = [m for m in metrics if m is not None]
    if not present:
        return {}
    return {
        "mrr": mean(m.mrr for m in present),
        "ndcg": mean(m.ndcg for m in present),
        "keyword_coverage": mean(m.keyword_coverage for m in present),
        "source_hit": mean(1.0 if m.source_hit else 0.0 for m in present),
    }


def summarize_retrieval(results: Sequence[RetrievalCaseResult]) -> RetrievalSummary:
    means = _retrieval_means([r.retrieval for r in results])
    return RetrievalSummary(cases=len(results), **means)


def summarize_answers(results: Sequence[CaseResult]) -> AnswerSummary:
    judged = [r.judge for r in results if r.judge]
    checks = [c.passed for r in results for c in r.checks]
    return AnswerSummary(
        cases=len(results),
        pass_rate=mean(1.0 if r.passed else 0.0 for r in results),
        checks_pass_rate=mean(1.0 if ok else 0.0 for ok in checks) if checks else 0.0,
        judge={k: mean(j.scores[k] for j in judged) for k in judged[0].scores} if judged else {},
        agent_retrieval=_retrieval_means([r.agent_retrieval for r in results]),
        latency_s=mean(r.latency_s for r in results),
    )


def by_category[R: (RetrievalCaseResult, CaseResult), S](
    results: Sequence[R], summarize: Callable[[list[R]], S]
) -> dict[str, S]:
    groups: dict[str, list[R]] = defaultdict(list)
    for r in results:
        groups[r.case.category].append(r)
    return {category: summarize(group) for category, group in groups.items()}
