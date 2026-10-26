---
paths:
  - "backend/app/db/**/*.py"
  - "backend/alembic/**"
  - "backend/app/repositories/**/*.py"
---
# Database

Before changing models, DAOs, repositories or migrations, read `docs/database.md`. New revision:
`make migration m="..."`, then rename to the next number and tidy it; new `public` tables enable
RLS; verify with `make migrate-check` and `make migrate-roundtrip`.
