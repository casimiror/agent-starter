from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import Settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Provider-agnostic chat model. OpenRouter speaks the OpenAI protocol."""
    provider = settings.llm_provider
    base_url = settings.llm_base_url
    if provider == "openrouter":
        provider, base_url = "openai", base_url or OPENROUTER_BASE_URL

    kwargs: dict = {"api_key": settings.llm_api_key, "temperature": settings.llm_temperature}
    if base_url:
        kwargs["base_url"] = base_url
    return init_chat_model(settings.llm_model, model_provider=provider, **kwargs)
