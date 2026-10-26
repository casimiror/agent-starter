from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import Settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_chat_model(
    settings: Settings, provider: str | None = None, model: str | None = None
) -> BaseChatModel:
    """Provider-agnostic chat model (LLM_PROVIDER / LLM_MODEL by default). OpenRouter speaks the
    OpenAI protocol. The client retries timeouts, 429 and 5xx itself (LLM_MAX_RETRIES)."""
    provider, model = provider or settings.llm_provider, model or settings.llm_model
    same_provider = provider == settings.llm_provider
    api_key = settings.llm_api_key if same_provider else _provider_key(settings, provider)
    base_url = settings.llm_base_url if same_provider else None
    if provider == "openrouter":
        provider, base_url = "openai", base_url or OPENROUTER_BASE_URL

    kwargs: dict = {
        "api_key": api_key,
        "temperature": settings.llm_temperature,
        "timeout": settings.llm_timeout,
        "max_retries": settings.llm_max_retries,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return init_chat_model(model, model_provider=provider, **kwargs)


def build_chat_models(settings: Settings) -> list[BaseChatModel]:
    """The primary model, then each LLM_FALLBACKS entry ("provider:model") in order. The agent
    tries the next one when a model still fails after its retries."""
    models = [build_chat_model(settings)]
    for entry in settings.llm_fallbacks:
        provider, sep, model = entry.partition(":")
        if not sep or not model:
            raise ValueError(f"LLM_FALLBACKS entry {entry!r} must be 'provider:model'")
        models.append(build_chat_model(settings, provider, model))
    return models


def _provider_key(settings: Settings, provider: str) -> str:
    keys = {
        "openrouter": settings.openrouter_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }
    if provider not in keys:
        raise ValueError(f"unknown LLM provider {provider!r}")
    if not keys[provider]:
        raise ValueError(f"fallback on {provider} needs {provider.upper()}_API_KEY")
    return keys[provider]
