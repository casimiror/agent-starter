from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from app.agents.builder import AgentBuilder
from app.core.config import Settings
from app.guardrails.input import MaxLengthGuardrail, PromptInjectionGuardrail
from app.guardrails.output import AllowedLinksGuardrail


def build_assistant_agent(
    models: list[BaseChatModel], tools: list[BaseTool], settings: Settings
) -> CompiledStateGraph:
    """`models`: the primary model first, then its fallbacks (`build_chat_models`)."""
    primary, *fallbacks = models
    return (
        AgentBuilder(settings.app_name)
        .with_llm(primary)
        .with_fallbacks(fallbacks)
        .with_prompt_file("assistant.md")
        .with_tools(tools)
        .with_input_guardrails(
            [MaxLengthGuardrail(settings.max_input_chars), PromptInjectionGuardrail()]
        )
        .with_output_guardrails([AllowedLinksGuardrail(settings.allowed_links)])
        .build()
    )
