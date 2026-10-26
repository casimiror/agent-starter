"""Run the dataset and keep one JSON per run. Two evaluations, as in the RAG course:

- **retrieval** (the RAG): the knowledge tool's search on each question. No LLM, seconds. Only when
  the project has a knowledge tool (`registry.build_retriever`).
- **answer** (the LLM): the real assistant agent answers, deterministic checks and a judge score it.

With Langfuse configured a run goes through `run_experiment`: every case is a trace linked to an
experiment on the `<APP_NAME>-eval` dataset, with its scores attached. Without Langfuse it is a
plain thread pool. Either way the JSON is what the /eval page reads.
"""

import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.language_models import BaseChatModel
from langfuse import Evaluation, get_client
from langfuse.langchain import CallbackHandler
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.core.config import BACKEND_DIR, Settings
from app.core.llm import build_chat_model
from app.evals.agent_run import build_eval_agent, eval_tool_deps, run_agent
from app.evals.checks import run_checks
from app.evals.dataset import EvalCase
from app.evals.judge import judge_answer
from app.evals.results import (
    AnswerRun,
    CaseResult,
    RetrievalCaseResult,
    RetrievalRun,
    by_category,
    summarize_answers,
    summarize_retrieval,
)
from app.evals.retrieval import score_retrieval
from app.tools.registry import build_retriever

RUNS_DIR = BACKEND_DIR / "eval_runs"

Progress = Callable[[int, int], None]


def _new_run_id(kind: str) -> str:
    return f"{kind}-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class NoRetrieverError(Exception):
    """The project has no knowledge tool, so there is no retrieval to evaluate."""

    def __str__(self) -> str:
        return "No knowledge tool: add one with /new-tool (recipe knowledge-search)."


class Evaluator:
    def __init__(self, settings: Settings, *, use_langfuse: bool = True) -> None:
        self.settings = settings
        self.retriever = build_retriever(eval_tool_deps(settings))
        self.dataset_name = f"{settings.app_name}-eval"
        self.use_langfuse = use_langfuse and settings.langfuse_enabled

    # Built on first use, so a retrieval run needs neither an LLM key nor a model.
    @cached_property
    def agent(self) -> CompiledStateGraph:
        return build_eval_agent(self.settings)

    @cached_property
    def judge(self) -> BaseChatModel:
        update = {"llm_model": self.settings.eval_judge_model, "llm_temperature": 0.0}
        return build_chat_model(self.settings.model_copy(update=update))

    # --- one case -----------------------------------------------------------------------------

    def retrieve_case(self, case: EvalCase) -> RetrievalCaseResult:
        """The knowledge tool's ranking for the question, exactly as the agent would get it."""
        assert self.retriever is not None
        docs = self.retriever.search(case.question)
        metrics = score_retrieval(case.keywords, case.expected_sources, docs)
        assert metrics is not None  # retrieval runs only take cases with keywords
        return RetrievalCaseResult(case=case, retrieval=metrics)

    def answer_case(self, case: EvalCase) -> CaseResult:
        callbacks = [CallbackHandler()] if self.use_langfuse else []
        run = run_agent(self.agent, case.question, callbacks)
        judge, judge_error = None, None
        if run.error is None:
            try:
                judge = judge_answer(self.judge, case, run)
            except Exception as exc:  # noqa: BLE001 - keep the case, report the judge failure
                judge_error = repr(exc)
        return CaseResult(
            case=case,
            reply=run.reply,
            blocked_by=run.blocked_by,
            tool_calls=run.tool_calls,
            agent_retrieval=score_retrieval(case.keywords, case.expected_sources, run.retrieved),
            checks=run_checks(case, run),
            judge=judge,
            judge_error=judge_error,
            latency_s=run.latency_s,
        )

    # --- whole runs ---------------------------------------------------------------------------

    def run_retrieval(
        self, cases: list[EvalCase], *, on_progress: Progress | None = None
    ) -> RetrievalRun:
        if self.retriever is None:
            raise NoRetrieverError
        cases = [c for c in cases if c.keywords]  # behaviour cases have nothing to retrieve
        run_id, started = _new_run_id("retrieval"), datetime.now(UTC)
        results, url = self._execute(
            run_id,
            cases,
            self.retrieve_case,
            RetrievalCaseResult,
            _retrieval_scores,
            concurrency=8,  # no LLM calls: only bounded by Langfuse uploads
            on_progress=on_progress,
        )
        return RetrievalRun(
            id=run_id,
            started_at=started,
            finished_at=datetime.now(UTC),
            summary=summarize_retrieval(results),
            by_category=by_category(results, summarize_retrieval),
            results=results,
            langfuse_url=url,
        )

    def run_answers(
        self, cases: list[EvalCase], *, concurrency: int = 4, on_progress: Progress | None = None
    ) -> AnswerRun:
        run_id, started = _new_run_id("answer"), datetime.now(UTC)
        results, url = self._execute(
            run_id,
            cases,
            self.answer_case,
            CaseResult,
            _answer_scores,
            concurrency=concurrency,
            on_progress=on_progress,
        )
        return AnswerRun(
            id=run_id,
            started_at=started,
            finished_at=datetime.now(UTC),
            bot_model=self.settings.llm_model,
            judge_model=self.settings.eval_judge_model,
            summary=summarize_answers(results),
            by_category=by_category(results, summarize_answers),
            results=results,
            langfuse_url=url,
        )

    def _execute[R: BaseModel](
        self,
        run_id: str,
        cases: list[EvalCase],
        evaluate: Callable[[EvalCase], R],
        result_type: type[R],
        scores: Callable[..., list[Evaluation]],
        concurrency: int,
        on_progress: Progress | None,
    ) -> tuple[list[R], str | None]:
        done, lock = 0, Lock()

        def task(case: EvalCase) -> R:
            nonlocal done
            result = evaluate(case)
            with lock:
                done += 1
                if on_progress:
                    on_progress(done, len(cases))
            return result

        if self.use_langfuse:
            results, url = self._in_langfuse(run_id, cases, task, result_type, scores, concurrency)
        else:
            with ThreadPoolExecutor(concurrency) as pool:
                results, url = list(pool.map(task, cases)), None
        order = {case.id: i for i, case in enumerate(cases)}
        results.sort(key=lambda r: order[r.case.id])  # type: ignore[attr-defined]
        return results, url

    def _in_langfuse[R: BaseModel](
        self,
        run_id: str,
        cases: list[EvalCase],
        task: Callable[[EvalCase], R],
        result_type: type[R],
        scores: Callable[..., list[Evaluation]],
        concurrency: int,
    ) -> tuple[list[R], str | None]:
        langfuse = get_client()
        _sync_dataset(langfuse, self.dataset_name, cases)
        by_id = {case.id: case for case in cases}
        items = [i for i in langfuse.get_dataset(self.dataset_name).items if i.id in by_id]

        def lf_task(*, item: Any, **_: Any) -> dict[str, Any]:
            return task(by_id[item.id]).model_dump(mode="json")

        experiment = langfuse.run_experiment(
            name=self.dataset_name,
            run_name=run_id,
            description=f"bot {self.settings.llm_model}, judge {self.settings.eval_judge_model}",
            data=items,
            task=lf_task,
            evaluators=[scores],
            max_concurrency=concurrency,
            metadata={"kind": run_id.split("-")[0], "bot_model": self.settings.llm_model},
        )
        langfuse.flush()
        results = []
        for item_result in experiment.item_results:
            if item_result.output is None:  # the task raised; nothing to report for it
                continue
            result = result_type.model_validate(item_result.output)
            if isinstance(result, CaseResult):
                result.trace_id = item_result.trace_id
            results.append(result)
        return results, experiment.experiment_url


def _sync_dataset(langfuse: Any, dataset_name: str, cases: list[EvalCase]) -> None:
    """Upsert the dataset and its items: the dataset file is the source of truth."""
    langfuse.create_dataset(name=dataset_name, description="Agent evaluation (backend/app/evals)")
    for case in cases:
        langfuse.create_dataset_item(
            dataset_name=dataset_name,
            id=case.id,
            input={"question": case.question},
            expected_output={
                "reference_answer": case.reference_answer,
                "behavior": case.expected_behavior,
            },
            metadata=case.model_dump(exclude={"question", "reference_answer"}),
        )


def _retrieval_scores(*, output: Any, **_: Any) -> list[Evaluation]:
    m = RetrievalCaseResult.model_validate(output).retrieval
    return [
        Evaluation(name="mrr", value=m.mrr),
        Evaluation(name="ndcg", value=m.ndcg),
        Evaluation(name="keyword_coverage", value=m.keyword_coverage),
        Evaluation(name="source_hit", value=m.source_hit, data_type="BOOLEAN"),
    ]


def _answer_scores(*, output: Any, **_: Any) -> list[Evaluation]:
    result = CaseResult.model_validate(output)
    scores = [
        Evaluation(name="passed", value=result.passed, data_type="BOOLEAN"),
        Evaluation(
            name="checks_passed",
            value=all(c.passed for c in result.checks),
            data_type="BOOLEAN",
            comment="; ".join(f"{c.name}: {c.detail}" for c in result.checks if not c.passed),
        ),
    ]
    if result.judge:
        scores += [
            Evaluation(name=name, value=value, comment=result.judge.feedback)
            for name, value in result.judge.scores.items()
        ]
    if retrieval := result.agent_retrieval:
        scores += [
            Evaluation(name="agent_mrr", value=retrieval.mrr),
            Evaluation(name="agent_keyword_coverage", value=retrieval.keyword_coverage),
        ]
    return scores


def save_run(run: RetrievalRun | AnswerRun, directory: Path = RUNS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.id}.json"
    path.write_text(run.model_dump_json(indent=2))
    return path
