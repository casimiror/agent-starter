from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    llm_provider: str = "openrouter"
    llm_model: str = "google/gemini-3.5-flash-lite"
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_temperature: float = 0.2
    # Each model retries timeouts, 429 and 5xx with exponential backoff (the client's own retry),
    # then the agent moves to the next model in LLM_FALLBACKS.
    llm_timeout: float = 25.0
    llm_max_retries: int = 1
    # "provider:model" entries in order, e.g.
    # LLM_FALLBACKS='["openrouter:openai/gpt-5.6-mini", "anthropic:claude-haiku-5-5"]'.
    # Same provider as LLM_PROVIDER: uses LLM_API_KEY. Another provider: its own key below.
    llm_fallbacks: list[str] = []
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Any Postgres URL (normalized in app/db/url.py). Default: the docker compose `db` service;
    # keep it in sync with docker-compose.yml. On Vercel: Supabase's transaction pooler, either as
    # DATABASE_URL or as POSTGRES_URL (set by the Vercel Supabase integration).
    database_url: str = Field(
        default="postgresql+psycopg://app:app_local_pw@db:5432/app",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    # Vercel sets VERCEL=1 in every deployment: no connection pool, flush traces every request.
    serverless: bool = Field(default=False, validation_alias=AliasChoices("SERVERLESS", "VERCEL"))

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # LANGFUSE_BASE_URL is the SDK's current name; LANGFUSE_HOST still accepted. EU by default,
    # US projects use https://us.cloud.langfuse.com.
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )
    # Langfuse environment of every trace. Vercel sets VERCEL_ENV (production / preview), so the
    # online judge in Langfuse can sample only production traffic.
    langfuse_environment: str = Field(
        default="development",
        validation_alias=AliasChoices("LANGFUSE_TRACING_ENVIRONMENT", "VERCEL_ENV"),
    )

    rate_limit_chat: str = "10/minute"
    # Votes are cheap (no LLM call) but still writes: looser limit than chat.
    rate_limit_feedback: str = "30/minute"
    # Where slowapi counts requests. memory:// is per process (per instance on Vercel); a Redis
    # URL (e.g. Upstash, rediss://...) makes the limit global across instances.
    rate_limit_storage_uri: str = "memory://"
    max_input_chars: int = 2000
    max_history_messages: int = 20

    # Logs go to stdout, one JSON object per line (Vercel and Docker collect them); "text" is
    # easier to read in a local terminal.
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Shown in the API title and the agent's Langfuse traces. The UI's name lives in
    # frontend/src/config.ts.
    app_name: str = "assistant"
    # The only URL prefixes the agent may write (AllowedLinksGuardrail). Everything else is
    # replaced with a safe reply. JSON list in env: ALLOWED_LINKS='["https://example.com"]'.
    allowed_links: list[str] = []

    # Offline evaluation (app/evals). Off everywhere except local runs: it calls the LLM for every
    # case, so it must never be reachable on the deployed app.
    eval_enabled: bool = False
    eval_judge_model: str = "google/gemini-3.8-flash"

    # Built React app. The Docker image and the Vercel build both put it in backend/static.
    frontend_dist: Path = BACKEND_DIR / "static"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
