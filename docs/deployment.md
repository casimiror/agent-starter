# Deployment

Production runs on Vercel (one FastAPI function plus the UI on its CDN) with Supabase Postgres.
Docker is only for local work; Vercel does not use it.

## How Vercel runs the project

On every push Vercel clones the repo, enters the Root Directory `backend/` and:

1. Detects the FastAPI preset from `pyproject.toml` (`[tool.vercel] entrypoint = "app.main:app"`).
2. Installs Python 3.12 (`.python-version`) and the dependencies from `uv.lock`.
3. Runs `[tool.vercel.scripts] build` = `sh vercel-build.sh`: `npm ci && npm run build` in
   `../frontend`, then copies `dist/` to `backend/static` (the default `FRONTEND_DIST`).
4. Deploys FastAPI as one Vercel Function (`vercel.json`: `maxDuration` 60 s, tests excluded) and
   promotes `app.frontend()`'s files to the CDN.

Migrations are automatic: on every push to `main`, GitHub Actions runs `check` and then the
`migrate-supabase` job (`alembic upgrade head` through the session pooler, secret `SUPABASE_DB_URL`
in the `production` environment). Vercel deploys `main` in parallel, so for a minute the new code
may run against the old schema or the old code against the new one. Keep every migration backward
compatible: add tables and nullable columns first, remove them in a later release.
`make migrate-supabase` stays available for a manual run.

A Build Command set in the dashboard or `vercel.json` overrides the `pyproject.toml` script: leave
it empty or the UI is not built. Pushes to `main` deploy to production; other branches and PRs get
preview deployments.

| Local (Docker) | Vercel |
| --- | --- |
| `frontend` stage of the Dockerfile | `vercel-build.sh` |
| `runtime` stage, always-on `fastapi run` | one serverless function, scaled with traffic |
| compose `db` | Supabase transaction pooler |
| `migrate` service | none: run `make migrate-supabase` yourself, before the deploy |
| `.env` | Project → Settings → Environment Variables |

## Local vs Vercel settings

| | Local | Vercel |
| --- | --- | --- |
| Database | compose `db` (direct, port 5432) | Supabase transaction pooler (port 6543) |
| Connection pool | SQLAlchemy pool (5) | `NullPool`: Supavisor pools (`VERCEL=1` sets `serverless`) |
| Prepared statements | on | off (transaction mode can't use them) |
| Migrations | `make migrate` | `make migrate-supabase` (session pooler, port 5432) |
| Frontend | Vite (`make dev`) or `/app/static` in the image | built by `vercel-build.sh` into `backend/static`, served from the CDN |

## Setup: 0. GitHub (once per repo)

A repo created from the template copies files, not settings. Until this is done, the
`migrate-supabase` job skips with a warning instead of failing.

1. **Settings → Environments → New environment** `production`, deployment branches limited to
   `main` (or `gh api -X PUT repos/<owner>/<repo>/environments/production -F
   deployment_branch_policy[protected_branches]=false -F
   deployment_branch_policy[custom_branch_policies]=true`, then add `main` as a branch policy).
2. Add the secret `SUPABASE_DB_URL` (session pooler URL, step 1 below) to that environment:
   `gh secret set SUPABASE_DB_URL --env production`, pasting the value when asked.

## Setup: 1. Supabase

1. Create a project in a region close to your Vercel functions (e.g. `us-east-1` with Vercel's
   `iad1`).
2. **Connect** button: copy the **Transaction pooler** URL (port 6543) and the **Session pooler**
   URL (port 5432), with the database password filled in.
3. Put the session pooler URL in `.env` as `SUPABASE_DB_URL` and run `make migrate-supabase`.
   Migrations go through the session pooler because the direct `db.<ref>.supabase.co` host is
   IPv6-only. Every table has RLS on with no policies, so Supabase's REST API exposes nothing; the
   backend connects as the table owner.

## Setup: 2. Vercel

1. **Add New → Project**, import this GitHub repo.
2. **Root Directory**: `backend`. Keep "Include files outside the root directory in the Build
   Step" on (default): the build compiles `../frontend`. The FastAPI preset is detected from
   `pyproject.toml` (`[tool.vercel]`); `vercel.json` sets `maxDuration` 60 s for LLM turns.
3. **Environment variables** (Production and Preview):

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | Supabase transaction pooler URL (6543). Or install the Supabase integration, which sets `POSTGRES_URL` (read as a fallback). |
   | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | `openrouter`, `google/gemini-3.5-flash-lite`, your key |
   | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | your project's keys and region URL |
   | `APP_NAME`, `ALLOWED_LINKS` | the app name and the URL prefixes the agent may write (JSON list) |

   The limits have working defaults. Never set `EVAL_ENABLED` on Vercel.
4. **Settings → Functions → Region**: the same region as Supabase.
5. Deploy, then check `https://<app>.vercel.app/api/health` and send a chat message.

## Known limits on Vercel

- **Rate limit is per function instance** (slowapi in-memory storage); the client IP comes from
  Vercel's `x-real-ip`. For a global limit, point slowapi at Redis (e.g. Upstash).
- **Langfuse** traces are flushed after every response (`BackgroundTasks`), since an instance can
  freeze between requests.

## Verify a deploy

```bash
curl -sD - https://<project>.vercel.app/api/health   # 200, x-vercel-id starts with your region
```

- `/` and `/assets/*` answer with `x-vercel-cache: HIT` (served from the CDN).
- A chat message returns a reply; the conversation appears in Supabase and the trace in Langfuse
  under the visitor's user id.
- The build log shows `npm ci` and `vite build`; if not, a dashboard Build Command is overriding
  the script.
