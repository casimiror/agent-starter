# Conventions

## Git workflow

- **One branch per task**, created from an up-to-date `main` (or from the previous branch when
  tasks are explicitly stacked). Never commit straight to `main`.
- Branch names: `<type>/<short-kebab-description>`, with type one of `feat`, `fix`, `docs`, `ci`,
  `refactor`, `chore`. Example: `feat/message-feedback`.
- **Small commits, one concern each**, imperative subject (`Add ...`, `Fix ...`) under ~70
  characters, body explaining *why*. The history is reviewed.
- Before pushing: `make check` passes (lint, tests, migration check, UI build).
- Integrate through a pull request (`gh pr create`). The PR body says what changed, how it was
  verified, and anything not verified. Merge once CI passes; delete the branch after merging.
- **CI** (`.github/workflows/ci.yml`) runs `make ci` on every PR and push to `main`: lint, tests,
  migrations up/down on a fresh Postgres, `alembic check`, UI build, and the production image
  build. Same Docker commands as local, no secrets.
- **On merge to `main`** the `migrate-supabase` job applies pending migrations to Supabase (secret
  `SUPABASE_DB_URL` in the GitHub `production` environment) while Vercel deploys. Migrations must
  be backward compatible: add first, remove in a later release.

## Python (backend)

- Python 3.12, `ruff` (line length 100, rules `E F I UP B`) is the formatter and linter.
- Type hints on public functions. Pydantic models for anything crossing a boundary (HTTP, tools,
  domain).
- Names: modules and functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`.
  Builders `build_<thing>(...)`; DAOs `<Table>DAO`; repositories `<Aggregate>Repository`;
  ORM rows `<Table>Row`.
- Comments explain *why*, not what. Match the density of the surrounding code.
- Prompts are Markdown files in `app/agents/prompts/`, never inline strings.
- Errors returned to the model start with an UPPERCASE code (`NO_RESULTS:`).

## TypeScript (frontend)

- Strict TypeScript; no `any`. Components are function components in `PascalCase.tsx`; hooks are
  `useThing.ts`.
- Feature folders and layers as in `docs/architecture/frontend.md`.
- CSS: tokens and BEM class names as in `docs/design/frontend.md`.

## Tests

- Backend tests in `backend/tests/`, `test_<area>.py`, run with `make test`.
- Never call a real LLM in tests: use `GenericFakeChatModel` or fake repositories.
- Every tool and guardrail has a unit test; every bug fix gets a test that would have caught it.
- Tests that need a database are not in the default suite yet; migrations are checked with
  `make migrate-check` and `make migrate-roundtrip`.

## Commands

Everything runs through `docker compose` (`make <target>`). The only host commands are uv
dependency changes inside `backend/` (`uv add`, `uv remove`, `uv lock`).

## Secrets and PII

- Secrets only in `.env` (gitignored) or the Vercel dashboard. `.env.example` lists every variable
  with a safe placeholder.
- No emails, names or other PII in logs or Langfuse traces. Contact details a tool collects live
  only in their own tables.
