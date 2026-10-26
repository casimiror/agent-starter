---
description: Lint, test and build everything before a commit
---
Run, in order, from the repo root and stop at the first failure (show the error and fix it before
continuing). Everything runs in Docker (see CLAUDE.md > Commands); never on the host.

1. `docker compose build api` (picks up dependency or Dockerfile changes)
2. `docker compose run --rm --no-deps api sh -c "ruff check . && ruff format --check ."`
3. `docker compose run --rm --no-deps api pytest -q`
4. `docker compose run --rm api alembic check` (local `db` service: detects models that changed
   without a migration). If `.env` points `DATABASE_URL` at Supabase and it is unreachable, run
   `docker compose run --rm --no-deps api alembic upgrade head --sql > /dev/null` instead.
5. `docker compose run --rm --no-deps web sh -c "npm install && npm run build"`

Then delegate a review of the staged diff to the `verifier` subagent and report its findings.
Do not commit; summarize what passed and propose a commit message.
