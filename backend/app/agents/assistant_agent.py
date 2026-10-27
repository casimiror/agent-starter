from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from app.agents.builder import AgentBuilder
from app.core.config import Settings
from app.guardrails.base import Guardrail
from app.guardrails.input import MaxLengthGuardrail, PromptInjectionGuardrail
from app.guardrails.output import AllowedLinksGuardrail


ASSISTANT_PROMPT = "assistant.md"


def assistant_guardrails(settings: Settings) -> tuple[list[Guardrail], list[Guardrail]]:
    """The assistant's (input, output) guardrails. One definition for the graph and for the
    voice realtime channel, which runs the same checks on transcripts."""
    return (
        [MaxLengthGuardrail(settings.max_input_chars), PromptInjectionGuardrail()],
        [AllowedLinksGuardrail(settings.allowed_links)],
    )


def build_assistant_agent(
    models: list[BaseChatModel], tools: list[BaseTool], settings: Settings
) -> CompiledStateGraph:
    """`models`: the primary model first, then its fallbacks (`build_chat_models`)."""
    primary, *fallbacks = models
    input_guardrails, output_guardrails = assistant_guardrails(settings)
    return (
        AgentBuilder(settings.app_name)
        .with_llm(primary)
        .with_fallbacks(fallbacks)
        .with_prompt_file(ASSISTANT_PROMPT)
        .with_tools(tools)
        .with_input_guardrails(input_guardrails)
        .with_output_guardrails(output_guardrails)
        .build()
    )
