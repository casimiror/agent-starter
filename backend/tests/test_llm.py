import pytest

from app.core.config import Settings
from app.core.llm import OPENROUTER_BASE_URL, build_chat_models


def _settings(**overrides) -> Settings:
    # Explicit values: the container's env (from .env) must not leak into these tests.
    base = {"llm_api_key": "sk-primary", "llm_timeout": 12, "llm_max_retries": 3}
    return Settings(_env_file=None, **base | {"llm_fallbacks": []} | overrides)


def test_primary_model_gets_timeout_retries_and_openrouter_url():
    [primary] = build_chat_models(_settings())
    assert primary.model_name == "google/gemini-3.5-flash-lite"
    assert primary.request_timeout == 12 and primary.max_retries == 3
    assert primary.openai_api_base == OPENROUTER_BASE_URL


def test_fallbacks_follow_in_order_with_their_own_keys():
    settings = _settings(
        llm_fallbacks=["openrouter:openai/gpt-5.6-mini", "anthropic:claude-haiku-5-5"],
        anthropic_api_key="sk-ant",
    )
    _, same_provider, other_provider = build_chat_models(settings)
    assert same_provider.model_name == "openai/gpt-5.6-mini"
    assert same_provider.openai_api_key.get_secret_value() == "sk-primary"
    assert other_provider.model == "claude-haiku-5-5"
    assert other_provider.anthropic_api_key.get_secret_value() == "sk-ant"


@pytest.mark.parametrize(
    ("fallback", "error"),
    [("gpt-5", "provider:model"), ("anthropic:claude-haiku-5-5", "ANTHROPIC_API_KEY")],
)
def test_bad_fallbacks_fail_at_startup(fallback, error):
    with pytest.raises(ValueError, match=error):
        build_chat_models(_settings(llm_fallbacks=[fallback]))
