# agent-starter — CLAUDE.md

Template for LLM agent projects. FastAPI serves the API and the built React app; a LangGraph agent
answers through its tools, behind input and output guardrails. Deploys to Vercel + Supabase. What
this project is for, its scenarios and what is out of scope: `plan.md`.

## Where to look

Read the relevant document before changing that area. Keep it current in the same commit.

| Area | Document |
| --- | --- |
| Backend layers, chat turn, tools, guardrails, observability | `docs/architecture/backend.md` |
| The agent graph; changing or adding agents | `backend/app/agents/README.md` |
| Channels beyond the web UI (WhatsApp, voice): shared pieces, identity, local tunnel | `docs/channels.md` |
| Frontend structure and patterns | `docs/architecture/frontend.md` |
| UI design: tokens, class naming, accessibility | `docs/design/frontend.md` |
| Schema, migrations, RLS, local vs Supabase connections | `docs/database.md` |
| Agent evaluation: dataset, `make eval`, judge, online judge | `docs/evaluation.md` |
| Vercel + Supabase deploy | `docs/deployment.md` |
| Git workflow, naming, tests, secrets | `docs/conventions.md` |

## Stack

Python 3.12 · FastAPI (`app.frontend()`) · LangGraph + LangChain v1 · SQLAlchemy 2 + psycopg 3 ·
Alembic · React 19 + Vite + TypeScript · Langfuse · OpenRouter (any provider via `LLM_PROVIDER`) ·
Twilio (optional WhatsApp and voice channels, `CHANNELS`; voice can use OpenAI Realtime) · Docker
locally, Vercel + Supabase in production. Do not swap a piece without updating `plan.md`.

## Workflow

- **IMPORTANT: every task gets its own branch** (`<type>/<kebab-name>`, e.g. `feat/message-feedback`),
  from `main` or from the previous branch when tasks are stacked. Never commit to `main`.
- Small commits, one concern each, imperative subject. `make check` must pass before pushing.
- Open a PR with `gh pr create`; merge when CI (`make ci` in GitHub Actions) passes. Merging
  migrates Supabase automatically, so migrations must be backward compatible (add first, remove
  later). Details: `docs/conventions.md`.
- Start a project: `/kickoff`. New tool: `/new-tool` (recipes). New agent: `/new-agent`. New channel
  (WhatsApp, voice): `/new-channel`. Deploy: `/deploy-setup`. Before committing: `/check`.

## Commands — everything runs in Docker

Every command runs through `docker compose` from the repo root, usually via `make` (`make help`).
Never run `uv run`, `python`, `pytest`, `ruff`, `alembic`, `fastapi`, `npm` or `node` on the host.
Only exception: uv dependency changes inside `backend/` (`uv add`, `uv remove`, `uv lock`; never
`pip install`), then rebuild with `--build`.

```bash
make env         # .env from .env.example, then fill LLM_API_KEY
make up          # prod-like on :8000 (db -> migrate -> app)
make dev         # api with reload :8001 + vite :5173
make test        # pytest          make lint / make format   # ruff
make migration m="add x"           # autogenerate; READ and tidy the file (docs/database.md)
make migrate     # local db        make migrate-supabase      # Supabase, before deploying
make migrate-check                 make migrate-roundtrip
make check       # lint + tests + migration check + UI build
make eval        # evaluate the real agent (LLM calls): local only, never in CI
```

## Rules that always apply

- Respect the backend layering (`routes -> services -> repositories -> daos`); wiring only in
  `app/api/deps.py`.
- Each layer (routes, services, clients, tests) groups a feature's or channel's files in a subfolder
  named after it (`api/routes/channels/<channel>/`, `services/channels/<channel>/`,
  `tests/channels/<channel>/`). A helper lives in the folder of what it serves (`format`, `twiml`,
  `session`...), not as a loose `<channel>_<thing>.py` at the layer root; a single-file channel may
  stay `<channel>.py` until it gets a second file. Shared code goes one level up
  (`twilio_security.py`, `conversations.py`) or in `core/` if generic. Details:
  `docs/architecture/backend.md`.
- The agent states only what its tools return or its prompt says. No invented prices, URLs, names
  or numbers; unknown -> say so or escalate. Every URL it may write is in `ALLOWED_LINKS`.
- Schema changes only via `app/db/models.py` + a new Alembic revision; never edit an applied one.
  Every new `public` table gets RLS enabled in its migration.
- Conversation history lives in the `messages` table, not a LangGraph checkpointer.
- Log with `logging.getLogger("app.<area>")` and fields in `extra` (`docs/architecture/backend.md`
  > Logging); never user text, replies or tool arguments.
- Secrets only via env (`.env`, Vercel). No PII in logs or Langfuse (`visitor_id` is an anonymous
  UUID). Keep `/api/chat` behind the rate limiter and the input length guardrail.
- Never call a real LLM in tests.

## Gotchas

- `DATABASE_URL` uses host `db`: it only resolves inside compose containers. Supabase URLs always go
  through `app/db/url.py` (`database_config`); Vercel uses the transaction pooler (6543), migrations
  the session pooler (5432).
- `app.frontend()` must be registered after all API routers.
- Run `fastapi dev` / `fastapi run` without a path (entrypoint in `[tool.fastapi]`).
- slowapi needs `request: Request` in the endpoint signature or the limiter silently does nothing.
- langchain-core 1.x: `message.text` is a property, not a method.
- React effects must use a block body: returning a value (e.g. `scrollIntoView`'s Promise) crashes.
- A repo created from this template does not copy GitHub settings: the `production` environment,
  its `SUPABASE_DB_URL` secret and the Vercel project are set up per project (`docs/deployment.md`).
