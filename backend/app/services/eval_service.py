import secrets
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Literal

from app.evals.dataset import EvalCase, load_dataset
from app.evals.runner import Evaluator, NoRetrieverError
from app.evals.store import RunStore

Kind = Literal["retrieval", "answer"]


class EvalBusyError(Exception):
    """An evaluation is already running; one at a time protects the shared LLM key."""


@dataclass
class EvalJob:
    id: str
    kind: Kind
    status: Literal["running", "done", "failed"]
    done: int
    total: int
    run_id: str | None = None
    error: str | None = None


class EvalService:
    """Starts evaluation runs in a background thread and reports their progress."""

    def __init__(
        self,
        evaluator: Callable[[], Evaluator],
        store: RunStore,
        *,
        retrieval_available: bool,
        dataset: Callable[[], list[EvalCase]] = load_dataset,
    ) -> None:
        self._evaluator = evaluator
        self._store = store
        self.retrieval_available = retrieval_available
        self._dataset = dataset
        self._jobs: dict[str, EvalJob] = {}
        self._lock = Lock()

    @property
    def store(self) -> RunStore:
        return self._store

    def start(self, kind: Kind, categories: list[str] | None = None) -> EvalJob:
        cases = [c for c in self._dataset() if not categories or c.category in categories]
        if kind == "retrieval":
            if not self.retrieval_available:
                raise NoRetrieverError
            cases = [c for c in cases if c.keywords]
        with self._lock:
            if any(job.status == "running" for job in self._jobs.values()):
                raise EvalBusyError
            job = EvalJob(secrets.token_hex(6), kind, "running", 0, len(cases))
            self._jobs[job.id] = job
        Thread(target=self._run, args=(job, cases), daemon=True).start()
        return job

    def get(self, job_id: str) -> EvalJob | None:
        return self._jobs.get(job_id)

    def _run(self, job: EvalJob, cases: list[EvalCase]) -> None:
        def progress(done: int, total: int) -> None:
            job.done, job.total = done, total

        try:
            evaluator = self._evaluator()
            if job.kind == "retrieval":
                run = evaluator.run_retrieval(cases, on_progress=progress)
            else:
                run = evaluator.run_answers(cases, concurrency=8, on_progress=progress)
            self._store.save(run)
            job.run_id, job.status = run.id, "done"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the page
            job.error, job.status = repr(exc), "failed"
