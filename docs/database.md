# Database

Postgres through SQLAlchemy 2 + psycopg 3. Locally the compose `db` service (Postgres 17);
deployed, Supabase. The browser never talks to the database.

## Schema

The ORM models in `backend/app/db/models.py` are the single source of truth.

| Table | Purpose | Notes |
| --- | --- | --- |
| `conversations` | one per chat | `visitor_id` (anonymous UUID, nullable, indexed); `channel in ('web','whatsapp','voice')`, default `web` (`docs/channels.md`); index on (`visitor_id`, `channel`, `created_at`) finds a visitor's latest conversation per channel |
| `messages` | every user/assistant message | `role in ('user','assistant')`; history source of truth |
| `message_feedback` | visitor's 👍/👎 on an assistant message | `message_id` unique, `rating in ('up','down')`, `updated_at`; removing a vote deletes the row |
| `alembic_version` | Alembic bookkeeping | RLS enabled in `0001` |

All app tables have `id` (UUID) and `created_at` (`TimestampedMixin`), and child rows cascade on
conversation delete.

## Migrations

- Change `models.py`, then `make migration m="..."`: it writes `backend/alembic/versions/
  000N_<slug>.py` with revision `"000N"` (the next number) in the style of `0001`
  (`alembic/script.py.mako`), formatted. **Read it**: drop the "auto generated" comments, check
  each column and constraint, and replace the RLS reminder with the real statement for a new table.
- Never edit an applied revision; add a new one.
- **Every new table in `public` gets `alter table ... enable row level security`** in the same
  migration. Supabase exposes `public` over REST; RLS with no policies means only the backend (the
  table owner) can read or write.
- Verify locally: `make migrate`, `make migrate-check`, `make migrate-roundtrip`.
- Supabase is migrated automatically when the PR merges (`migrate-supabase` job in GitHub
  Actions). Write migrations backward compatible: Vercel deploys in parallel. Manual run:
  `make migrate-supabase` (uses `SUPABASE_DB_URL` from `.env`).

## Local vs Supabase

`backend/app/db/url.py` (`database_config`) normalizes any URL; the app and Alembic both use it.

| | Local | Supabase from Vercel | Supabase for migrations |
| --- | --- | --- | --- |
| Variable | `DATABASE_URL` in `.env` | `DATABASE_URL` (or `POSTGRES_URL`) in Vercel | `SUPABASE_DB_URL` in `.env` |
| Endpoint | compose `db:5432` | transaction pooler `*.pooler.supabase.com:6543` | session pooler `*.pooler.supabase.com:5432` |
| Pool | SQLAlchemy pool (5) | `NullPool` (`VERCEL=1`) | `NullPool` (Alembic) |
| Prepared statements | on | off (`prepare_threshold=None`) | on |
| SSL | no | `sslmode=require` (added automatically) | `sslmode=require` |

The direct host `db.<ref>.supabase.co` is IPv6-only: unreachable from Vercel and from Docker on
most Macs, so it is not used.

## Access patterns

- DAOs: one per table, `BaseDAO[Row]` gives `insert`, `get`, `list_by`. Each call is its own short
  transaction (`sessionmaker.begin()`).
- Repositories turn rows into `app/domain` models; nothing above them sees SQLAlchemy.
- Persist a chat turn only after it succeeded.
