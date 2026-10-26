"""CLI: `make eval args="..."` (python -m app.evals)."""

import argparse
import os
import sys
from typing import get_args

from app.core import observability
from app.core.config import get_settings
from app.evals.dataset import Category, load_dataset
from app.evals.results import AnswerRun, RetrievalRun
from app.evals.runner import Evaluator, save_run


def _progress(done: int, total: int) -> None:
    print(f"\r  {done}/{total}", end="" if done < total else "\n", flush=True)


def _fmt(metrics: dict[str, float]) -> str:
    return ", ".join(f"{k} {v:.2f}" for k, v in metrics.items())


def _report(run: RetrievalRun | AnswerRun) -> None:
    s = run.summary
    if isinstance(run, RetrievalRun):
        print(f"RAG ({s.cases} cases): mrr {s.mrr:.2f}, ndcg {s.ndcg:.2f}, ", end="")
        print(f"keyword coverage {s.keyword_coverage:.0%}, source hit {s.source_hit:.0%}")
    else:
        print(f"LLM ({s.cases} cases): pass rate {s.pass_rate:.0%}, judge {_fmt(s.judge)}")
        failed = [r.case.id for r in run.results if not r.passed]
        if failed:
            print(f"  failed: {', '.join(failed)}")
    print(f"  saved eval_runs/{run.id}.json")
    if run.langfuse_url:
        print(f"  {run.langfuse_url}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the assistant agent on the dataset.")
    parser.add_argument(
        "--mode",
        choices=["retrieval", "answer", "all"],
        default="all",
        help="retrieval: the knowledge-base tool, no LLM; answer: agent + judge",
    )
    parser.add_argument("--category", action="append", choices=get_args(Category))
    parser.add_argument("--id", action="append", dest="ids", help="case id, repeatable")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-langfuse", action="store_true")
    args = parser.parse_args()

    # The LLM account is shared and limited: evaluations never run in CI (GitHub sets CI=true).
    if os.environ.get("CI", "").lower() == "true":
        print("make eval does not run in CI: it calls the LLM for every case.", file=sys.stderr)
        return 1

    cases = load_dataset()
    if args.category:
        cases = [c for c in cases if c.category in args.category]
    if args.ids:
        cases = [c for c in cases if c.id in args.ids]
    cases = cases[: args.limit] if args.limit else cases
    if not cases:
        print("no cases match", file=sys.stderr)
        return 1

    settings = get_settings()
    observability.init_observability(settings)
    evaluator = Evaluator(settings, use_langfuse=not args.no_langfuse)
    if args.mode in ("retrieval", "all") and evaluator.retriever is None:
        print("RAG evaluation skipped: no knowledge tool (/new-tool, recipe knowledge-search)")
        if args.mode == "retrieval":
            return 1
    elif args.mode in ("retrieval", "all"):
        print("RAG evaluation (knowledge-base search)")
        run = evaluator.run_retrieval(cases, on_progress=_progress)
        save_run(run)
        _report(run)
    if args.mode in ("answer", "all"):
        print("LLM evaluation (agent + judge)")
        run = evaluator.run_answers(cases, concurrency=args.concurrency, on_progress=_progress)
        save_run(run)
        _report(run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
