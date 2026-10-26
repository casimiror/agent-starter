from app.core.config import Settings


def test_langfuse_base_url_reads_current_and_legacy_names(monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    assert Settings(_env_file=None).langfuse_base_url == "https://us.cloud.langfuse.com"
    monkeypatch.delenv("LANGFUSE_BASE_URL")
    monkeypatch.setenv("LANGFUSE_HOST", "https://eu.example.com")
    assert Settings(_env_file=None).langfuse_base_url == "https://eu.example.com"


def test_database_url_falls_back_to_vercel_integration_name(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@h:6543/postgres")
    assert Settings(_env_file=None).database_url == "postgres://u:p@h:6543/postgres"
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit@h:6543/postgres")
    assert Settings(_env_file=None).database_url == "postgresql://explicit@h:6543/postgres"


def test_vercel_env_means_serverless(monkeypatch):
    monkeypatch.delenv("SERVERLESS", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert not Settings(_env_file=None).serverless
    monkeypatch.setenv("VERCEL", "1")
    assert Settings(_env_file=None).serverless


def test_langfuse_environment_follows_vercel(monkeypatch):
    monkeypatch.delenv("LANGFUSE_TRACING_ENVIRONMENT", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    assert Settings(_env_file=None).langfuse_environment == "development"
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert Settings(_env_file=None).langfuse_environment == "production"
