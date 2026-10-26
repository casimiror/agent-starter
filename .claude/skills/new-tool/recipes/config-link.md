# Recipe: config-link

The tool returns fixed information the project configures: a booking or contact link, a support
email, opening hours, a portal URL. The values live in `Settings` (env), never in the prompt or the
code, so production can change them without a deploy of new code.

## Settings: `backend/app/core/config.py`

```python
    # <What it is; who uses it.>
    <thing>_url: str = ""
```

Add it to `.env.example` (with a comment) and to the Vercel variables in `docs/deployment.md`.
If the agent may write the URL, add it to `ALLOWED_LINKS` too, or the output guardrail replaces
the reply. Better: build the allowed list in `assistant_agent.py` from both, so they can't drift:

```python
        .with_output_guardrails(
            [AllowedLinksGuardrail([*settings.allowed_links, settings.<thing>_url])]
        )
```

## Tool: `backend/app/tools/<area>/<tool_name>.py`

```python
from langchain_core.tools import BaseTool

from app.tools.builder import ToolBuilder


def build_<tool_name>_tool(<thing>_url: str) -> BaseTool:
    def get() -> str:
        if not <thing>_url:
            return "UNAVAILABLE: <thing> is not configured. <What the agent does instead>."
        return f"<Sentence the agent can relay, with {<thing>_url}>."

    return (
        ToolBuilder("<tool_name>")
        .describe("<What it returns>. Call it when the user asks <trigger>.")
        .handler(get)
        .build()
    )
```

No args model: the tool takes no arguments.

## Wiring

- `app/tools/registry.py`: `build_<tool_name>_tool(deps.settings.<thing>_url)` in
  `build_<agent>_tools` (settings are already in `ToolDeps`). Nothing else to wire.

## Tests: `backend/tests/test_<area>_tools.py`

```python
from app.tools.<area>.<tool_name> import build_<tool_name>_tool


def test_returns_the_configured_link():
    assert "https://example.com/x" in build_<tool_name>_tool("https://example.com/x").invoke({})


def test_unconfigured():
    assert build_<tool_name>_tool("").invoke({}).startswith("UNAVAILABLE")
```

## Prompt, evals

- Prompt: "To <do X>, call `<tool_name>` and give the link it returns. Never write a URL that a
  tool did not give you."
- Eval cases: `expected_tools: ["<tool_name>"]`, `forbidden` with a plausible made-up URL.
