"""Turn whatever Postgres URL the environment gives into what SQLAlchemy + psycopg 3 need.

Two targets share one code path:
- Local: the docker compose `db` service, a plain direct connection.
- Deployed: Supabase. Its dashboard and the Vercel integration hand out `postgres://` or
  `postgresql://` URLs, sometimes with non-libpq params (`supa=base-pooler.x`). On Vercel we use the
  Supavisor transaction pooler (port 6543), which does not support prepared statements.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import URL, make_url

DRIVER = "postgresql+psycopg"
TRANSACTION_POOLER_PORT = 6543
_SUPABASE_HOSTS = (".supabase.com", ".supabase.co")
# Added by Supabase / Vercel for other clients; psycopg rejects unknown connection options.
_NON_LIBPQ_PARAMS = {"supa", "pgbouncer"}


@dataclass(frozen=True)
class DatabaseConfig:
    url: URL
    connect_args: dict[str, Any] = field(default_factory=dict)

    @property
    def is_transaction_pooler(self) -> bool:
        return self.url.port == TRANSACTION_POOLER_PORT


def database_config(raw_url: str) -> DatabaseConfig:
    url = make_url(raw_url).set(drivername=DRIVER)
    query = {k: v for k, v in url.query.items() if k not in _NON_LIBPQ_PARAMS}
    if (url.host or "").endswith(_SUPABASE_HOSTS):
        query.setdefault("sslmode", "require")  # libpq defaults to "prefer", which may not encrypt
    url = url.set(query=query)

    connect_args: dict[str, Any] = {}
    if url.port == TRANSACTION_POOLER_PORT:
        # Transaction mode hands each transaction to any backend: server-side prepared
        # statements would leak between clients, so psycopg must never prepare.
        connect_args["prepare_threshold"] = None
    return DatabaseConfig(url=url, connect_args=connect_args)
