import pytest

from app.db.url import database_config

LOCAL = "postgresql+psycopg://app:app_local_pw@db:5432/app"
POOLER = "aws-0-us-east-1.pooler.supabase.com"


def test_local_url_is_untouched():
    db = database_config(LOCAL)
    assert db.url.render_as_string(hide_password=False) == LOCAL
    assert db.connect_args == {} and not db.is_transaction_pooler


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_any_postgres_scheme_uses_psycopg(scheme):
    assert database_config(f"{scheme}://u:p@{POOLER}:5432/postgres").url.drivername == (
        "postgresql+psycopg"
    )


def test_supabase_transaction_pooler_disables_prepared_statements_and_requires_ssl():
    # Shape of the Vercel Supabase integration's POSTGRES_URL.
    db = database_config(
        f"postgres://postgres.ref:pw@{POOLER}:6543/postgres?sslmode=require&supa=base-pooler.x"
    )
    assert db.is_transaction_pooler
    assert db.connect_args == {"prepare_threshold": None}
    assert dict(db.url.query) == {"sslmode": "require"}  # `supa` dropped: psycopg rejects it


def test_supabase_session_pooler_keeps_prepared_statements_and_adds_ssl():
    db = database_config(f"postgresql://postgres.ref:pw@{POOLER}:5432/postgres")
    assert db.connect_args == {}
    assert db.url.query["sslmode"] == "require"


def test_explicit_sslmode_is_kept():
    db = database_config(f"postgresql://u:p@{POOLER}:5432/postgres?sslmode=verify-full")
    assert db.url.query["sslmode"] == "verify-full"


def test_password_with_special_characters_survives():
    db = database_config(f"postgresql://postgres.ref:p%40ss%2Fw0rd@{POOLER}:6543/postgres")
    assert db.url.password == "p@ss/w0rd"
