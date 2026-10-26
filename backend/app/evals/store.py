"""The run JSON files, read back for the /eval page."""

import re
from pathlib import Path

from pydantic import TypeAdapter

from app.evals.results import AnswerRun, EvalRun, RetrievalRun
from app.evals.runner import RUNS_DIR, save_run

_RUN_ID = re.compile(r"^(retrieval|answer)-\d{8}-\d{6}-[0-9a-f]{4}$")
_RUN = TypeAdapter(EvalRun)


class RunStore:
    def __init__(self, directory: Path = RUNS_DIR) -> None:
        self._dir = directory

    def save(self, run: RetrievalRun | AnswerRun) -> None:
        save_run(run, self._dir)

    def get(self, run_id: str) -> RetrievalRun | AnswerRun | None:
        # The id becomes a file name: only accept the exact format the runner produces.
        if not _RUN_ID.match(run_id):
            return None
        path = self._dir / f"{run_id}.json"
        return _RUN.validate_json(path.read_bytes()) if path.exists() else None

    def list(self, kind: str | None = None) -> list[RetrievalRun | AnswerRun]:
        """Newest first. Run ids start with kind and a sortable UTC timestamp."""
        pattern = f"{kind}-*.json" if kind else "*.json"
        paths = sorted(self._dir.glob(pattern), key=lambda p: p.stem.split("-", 1)[1], reverse=True)
        return [_RUN.validate_json(p.read_bytes()) for p in paths if _RUN_ID.match(p.stem)]
