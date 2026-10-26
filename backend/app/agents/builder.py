from pathlib import Path
from typing import Self

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agents.state import AgentState
from app.guardrails.base import Guardrail, run_guardrails

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class AgentBuilder:
    """Composes LLM + prompt + tools + guardrails into one LangGraph graph.

    START -> input_guard --blocked--> END
                 |ok
               agent <-> tools
                 |done
           output_guard -> END
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._llm: BaseChatModel | None = None
        self._system_prompt = ""
        self._tools: list[BaseTool] = []
        self._input_guardrails: list[Guardrail] = []
        self._output_guardrails: list[Guardrail] = []

    def with_llm(self, llm: BaseChatModel) -> Self:
        self._llm = llm
        return self

    def with_prompt_file(self, filename: str, **variables: str) -> Self:
        self._system_prompt = (PROMPTS_DIR / filename).read_text().format(**variables)
        return self

    def with_tools(self, tools: list[BaseTool]) -> Self:
        self._tools = tools
        return self

    def with_input_guardrails(self, guardrails: list[Guardrail]) -> Self:
        self._input_guardrails = guardrails
        return self

    def with_output_guardrails(self, guardrails: list[Guardrail]) -> Self:
        self._output_guardrails = guardrails
        return self

    def build(self) -> CompiledStateGraph:
        if self._llm is None:
            raise ValueError(f"agent {self._name!r} needs an LLM")
        llm = self._llm.bind_tools(self._tools) if self._tools else self._llm
        system = SystemMessage(self._system_prompt)
        input_guardrails, output_guardrails = self._input_guardrails, self._output_guardrails

        def input_guard(state: AgentState) -> dict:
            result = run_guardrails(input_guardrails, state["messages"][-1].text)
            if result.allowed:
                return {"blocked_by": None}
            return {"blocked_by": result.reason, "messages": [AIMessage(result.replacement)]}

        def agent(state: AgentState) -> dict:
            return {"messages": [llm.invoke([system, *state["messages"]])]}

        def output_guard(state: AgentState) -> dict:
            last = state["messages"][-1]
            result = run_guardrails(output_guardrails, last.text)
            if result.allowed:
                return {}
            # Same id -> replaces the unsafe message instead of appending.
            return {
                "blocked_by": result.reason,
                "messages": [AIMessage(result.replacement, id=last.id)],
            }

        graph = StateGraph(AgentState)
        graph.add_node("input_guard", input_guard)
        graph.add_node("agent", agent)
        graph.add_node("output_guard", output_guard)
        graph.add_edge(START, "input_guard")
        graph.add_conditional_edges(
            "input_guard", lambda s: END if s.get("blocked_by") else "agent"
        )
        if self._tools:
            graph.add_node("tools", ToolNode(self._tools))
            graph.add_conditional_edges(
                "agent", tools_condition, {"tools": "tools", END: "output_guard"}
            )
            graph.add_edge("tools", "agent")
        else:
            graph.add_edge("agent", "output_guard")
        graph.add_edge("output_guard", END)
        return graph.compile(name=self._name)
