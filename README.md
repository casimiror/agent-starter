# agent-starter

Template for LLM agent projects, extracted from a production support chatbot. Start a project with
the architecture, the tooling and the deploy already in place, and spend the time on the agent.

**Repository**: https://github.com/casimiror/agent-starter

## What you get

- **FastAPI** serves `POST /api/chat`, feedback endpoints and the built React UI
  (`app.frontend()`), one container locally and one Vercel function in production.
- **LangGraph** agent built with `AgentBuilder`: `input_guard -> agent <-> tools -> output_guard`.
  It ships without domain tools: add them with `/new-tool`. Diagram and how to modify or create
  agents: [backend/app/agents/](backend/app/agents/README.md).
- **Guardrails**: input length, prompt-injection heuristics, only `ALLOWED_LINKS` in replies.
- **Data**: Postgres (Supabase in production) through DAOs and repositories; Alembic migrations
  with RLS on every table; conversations, messages and 👍/👎 feedback.
- **Observability**: Langfuse, one trace per turn; session = conversation, user = anonymous visitor
  id; production traces tagged with the `production` environment.
- **Evaluation**: dataset, RAG metrics and an LLM judge on the real agent, a `/eval` page,
  Langfuse experiments, and prompts for an online judge on production traffic:
  [backend/app/evals/](backend/app/evals/README.md).
- **Resilience**: per-model timeout and retries, then fallback models (another provider too).
- **Structured logs**: JSON lines with a request id, no PII.
- **Rate limiting** per IP on `/api/chat`, global with Redis (`RATE_LIMIT_STORAGE_URI`).
- **CI**: lint, tests, migrations and UI build on every PR; Supabase migrated automatically on merge.
- **Claude Code setup**: `CLAUDE.md`, path rules, `/new-tool`, `/new-agent`, `/check` and a
  `verifier` subagent.

Documentation: [docs/](docs/README.md) (architecture, design, conventions, database, deployment,
evaluation). Project plan: [plan.md](plan.md) (a template to fill).

## Start a project

1. On GitHub: **Use this template → Create a new repository**, then clone it.
2. `make env`, put your OpenRouter key in `LLM_API_KEY`, then `make up`: the app runs on
   http://localhost:8000 with a generic assistant.
3. Fill `plan.md` (goal, scenarios, agents and tools), then the prompt
   (`backend/app/agents/prompts/assistant.md`), the UI texts (`frontend/src/config.ts`) and
   `APP_NAME` / `ALLOWED_LINKS` in `.env`.
4. Add tools with `/new-tool`, and eval cases for each scenario.
5. Deploy: [docs/deployment.md](docs/deployment.md) (GitHub environment, Supabase, Vercel).

## Run

Everything runs in Docker through `make` (`make help`).

| Command | Does |
| --- | --- |
| `make env` | create `.env` from `.env.example` |
| `make up` | prod-like: db, migrations and the app on http://localhost:8000 |
| `make dev` | API with reload on :8001 and Vite on http://localhost:5173 |
| `make check` | lint, tests, migration check and UI build (run before every commit) |
| `make ci` | what GitHub Actions runs (fresh db: migrate first) |
| `make migration m="..."` | new Alembic revision from the models; read and tidy it |
| `make eval` | evaluate the agent on the dataset (LLM calls). Local only |
| `make down` / `make reset-db` | stop containers / also wipe the local database |

### Configuration

All settings come from env (`backend/app/core/config.py`, documented in `.env.example`):

- **LLM**: `LLM_PROVIDER` (`openrouter`, `anthropic`, `openai`), `LLM_MODEL`, `LLM_API_KEY`;
  resilience: `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_FALLBACKS` (models tried in order when one fails).
- **Logs**: `LOG_FORMAT` (`json` in production, `text` locally), `LOG_LEVEL`.
- **App**: `APP_NAME`, `ALLOWED_LINKS` (JSON list of URL prefixes the agent may write).
- **Database**: `DATABASE_URL` (local compose `db` by default), `SUPABASE_DB_URL` for migrations.
- **Langfuse**: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (optional).
- **Evaluation**: `EVAL_ENABLED` (local only), `EVAL_JUDGE_MODEL`.

## Evaluate the agent locally

With `EVAL_ENABLED=true` in `.env`, `make dev` and open http://localhost:5173/eval, or run
`make eval`. Results go to `backend/eval_runs/*.json` and, with Langfuse keys, to a Langfuse
experiment. Never in CI. Details: [docs/evaluation.md](docs/evaluation.md).

## Deploy

Vercel (FastAPI preset, Root Directory `backend/`) with Supabase Postgres. Setup, environment
variables, migrations and how to verify a deploy: [docs/deployment.md](docs/deployment.md).
