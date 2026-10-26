# Evaluator

Offline evaluation of the agent, adapted from the evaluator of the RAG course (retrieval MRR /
nDCG / keyword coverage plus an LLM-as-a-judge): it runs **the real agent** (same prompt, tools,
guardrails and model as production) on `dataset.jsonl` and scores it twice:

| Evaluation | What it tests | Metrics | Cost |
| --- | --- | --- | --- |
| **RAG** | the knowledge tool's search for each question (only when the project has one) | MRR, nDCG, keyword coverage, source hit | no LLM, seconds |
| **LLM** | the agent's replies: deterministic checks + an LLM judge | pass rate, accuracy, completeness, relevance, groundedness, behaviour (1-5) | 2-4 LLM calls per case |

Every run is saved as one JSON file and, with Langfuse configured, as a **Langfuse experiment** on
the `<APP_NAME>-eval` dataset: one trace of the agent per case with its scores attached. Results
can be read in the `/eval` page, in the CLI output, or in Langfuse.

> **Local only.** It calls the shared, rate-limited LLM account for every case: it is never mounted
> on the deployed app and never runs in CI (the CLI exits with an error when `CI=true`).

## Run it locally

1. In `.env` (copy of `.env.example`):

   | Variable | Value |
   | --- | --- |
   | `EVAL_ENABLED` | `true`: mounts `/api/evals` and turns on the `/eval` page |
   | `LLM_API_KEY` | your OpenRouter key (the agent and the judge use it) |
   | `EVAL_JUDGE_MODEL` | judge model, default `google/gemini-3.8-flash` |
   | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | optional: without them runs are saved only as JSON |

2. Either use the page:

   ```bash
   make dev        # then open http://localhost:5173/eval
   ```

   or the CLI:

   ```bash
   make eval                                            # RAG (if any) + LLM, all cases
   make eval args="--mode retrieval"                    # RAG only, no LLM
   make eval args="--mode answer --category guardrail"  # LLM evaluation of one category
   make eval args="--id scope-01 --no-langfuse"         # one case, JSON only
   ```

Results land in `backend/eval_runs/<retrieval|answer>-<timestamp>.json` (gitignored).

## The `/eval` page

Two sections, each with its own **Run evaluation** button and progress bar (the run happens in a
background job; one evaluation at a time). Colours use the course's thresholds: ratios green >= 0.9,
amber >= 0.75; judge scores green >= 4.5, amber >= 4.0.

- **RAG evaluation**: metric cards, average MRR by category, and every case with what the tool
  returned, worst first. Without a knowledge tool the section explains how to add one.
- **LLM evaluation**: pass rate and judge scores, average accuracy by category, and the failing
  cases with the judge's feedback. A row expands to the question, expected behaviour, reply, tools,
  retrieved sections and failed checks.

## In Langfuse

The dataset file is synced to the Langfuse dataset `<APP_NAME>-eval` on every run (items upserted by
case id), and each run becomes an experiment on it: compare runs (prompt or model changes) in its
**Experiments** tab, open one to see each case's trace and scores.

## How a case is scored

```
dataset.jsonl ─┬─ RAG: knowledge search(question) ── keywords in results? ── MRR, nDCG, coverage, source hit
               │
               └─ LLM: real agent answers ──┬─ agent retrieval: same metrics on its own searches
                  (tools that write use     ├─ checks: blocked? expected tools? forbidden strings?
                   in-memory repositories)  └─ judge: accuracy, completeness, relevance,
                                               groundedness, behaviour (1-5)

passed = every check passes and judge accuracy >= 4 and behaviour >= 4
```

- **Keywords** are matched case- and whitespace-insensitively in the retrieved text.
- The **agent retrieval** is compared with the RAG evaluation to tell an index problem (the RAG
  evaluation fails too) from a query problem (only the agent fails).
- The **judge** sees the question, expected behaviour, reference answer, retrieved context, tools
  called and reply. Its rubric is `prompts/judge.md`; keep its "how the assistant is supposed to
  behave" section in line with the agent's prompt.

## Dataset

`dataset.jsonl`, one case per line; categories and fields are in
[`docs/evaluation.md`](../../../docs/evaluation.md#dataset). The template ships 5 cases that need no
tools; replace them with the project's own (`/kickoff` drafts them from `plan.md`).

To add a case: next id in its category, keywords copied from the documents in `expected_sources`,
then `make test` and `make eval args="--id <new-id>"`.

## Files

| File | Role |
| --- | --- |
| `dataset.jsonl`, `dataset.py` | the cases and their Pydantic model |
| `agent_run.py` | builds and runs the real agent; `eval_tool_deps` gives tools in-memory repositories |
| `retrieval.py` | MRR, nDCG, coverage (from the course); the shared result format is in `app/domain/retrieval.py` |
| `checks.py` | deterministic checks |
| `judge.py`, `prompts/judge.md` | the LLM judge and its rubric |
| `prompts/online_*.md` | prompts of the online judge in Langfuse, for production traces ([setup](../../../docs/evaluation.md#online-evaluation-in-langfuse)) |
| `results.py` | per-case and per-run models, summaries by category; what the JSON contains |
| `runner.py` | runs a RAG or LLM evaluation, through `run_experiment` when Langfuse is configured |
| `store.py` | reads the run JSON files back for the page |
| `__main__.py` | the CLI behind `make eval` |

The API (`app/api/routes/evals.py`, `app/services/eval_service.py`) and the page
(`frontend/src/features/eval/`) are described in [`docs/evaluation.md`](../../../docs/evaluation.md).
