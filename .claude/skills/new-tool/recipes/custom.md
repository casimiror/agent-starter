# Recipe: custom

For a tool that fits no other recipe (a calculation, a validation, a lookup in code). Same shape:
one file, a builder function, `ToolBuilder`, a unit test.

## Tool: `backend/app/tools/<area>/<tool_name>.py`

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.tools.builder import ToolBuilder


class <ToolName>Args(BaseModel):
    <arg>: <type> = Field(description="<What it is, its unit or format>")


def build_<tool_name>_tool(<dependencies>) -> BaseTool:
    def run(<arg>: <type>) -> str:
        ...
        return "<short result the agent can relay>"

    return (
        ToolBuilder("<tool_name>")
        .describe("<What it returns>. Call it when <trigger>.")
        .args(<ToolName>Args)
        .handler(run)
        .build()
    )
```

- Pure logic stays in the handler or a helper next to it; anything that touches the database goes
  through a repository (see db-write), anything external through a client (see http-api).
- Need the conversation? Add `config: RunnableConfig` to the handler and read
  `config["configurable"]["conversation_id"]`; LangChain hides it from the model.
- Exceptions go back to the model as the tool result (`handle_tool_error=True` in `ToolBuilder`);
  prefer returning a coded string (`INVALID: ...`) for expected failures.

## Wiring, tests, prompt, evals

As in the skill's rules: register in `build_<agent>_tools`, dependencies in `ToolDeps` /
`get_tool_deps` / `eval_tool_deps`, a test calling `tool.invoke({...})` for the normal case and
each failure code, a line in the prompt, and eval cases expecting the tool.
