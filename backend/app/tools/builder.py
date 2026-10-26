from collections.abc import Callable
from typing import Any, Self

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel


class ToolBuilder:
    """Fluent builder so every tool is declared the same way.

    ToolBuilder("search_knowledge").describe("...").args(SearchArgs).handler(fn).build()

    A handler may declare `config: RunnableConfig` to read per-turn context
    (e.g. config["configurable"]["conversation_id"]); LangChain injects it and hides it
    from the schema the model sees.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._description: str | None = None
        self._args_schema: type[BaseModel] | None = None
        self._handler: Callable[..., Any] | None = None

    def describe(self, description: str) -> Self:
        self._description = description
        return self

    def args(self, schema: type[BaseModel]) -> Self:
        self._args_schema = schema
        return self

    def handler(self, fn: Callable[..., Any]) -> Self:
        self._handler = fn
        return self

    def build(self) -> BaseTool:
        if not self._description:
            raise ValueError(f"tool {self._name!r} needs a description (the model reads it)")
        if self._handler is None:
            raise ValueError(f"tool {self._name!r} needs a handler")
        return StructuredTool.from_function(
            func=self._handler,
            name=self._name,
            description=self._description,
            args_schema=self._args_schema,
            # Exceptions go back to the model as the tool result instead of crashing the turn.
            handle_tool_error=True,
        )
