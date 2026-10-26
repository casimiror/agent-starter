---
description: Scaffold a new agent tool with ToolBuilder, register it, and test it
argument-hint: <tool_name> <what it does>
---
Create a new tool for the assistant agent: $ARGUMENTS

1. Pick the area folder under `backend/app/tools/` (create one if none fits) and add
   `<tool_name>.py` exposing `build_<tool_name>_tool(deps) -> BaseTool`, built with
   `ToolBuilder` (`app/tools/builder.py`).
2. Args go in a pydantic model with a `Field(description=...)` per arg: the model reads them.
3. The description says *when* to call the tool, not only what it does.
4. Data access goes through a repository passed in as a dependency, never a DAO or session.
5. Per-turn context (conversation id) comes from `config: RunnableConfig`, not from args.
6. Return short strings; failure cases start with an UPPERCASE code the prompt can react to
   (e.g. `NO_RESULTS:`).
7. Register it in `build_assistant_tools` (`app/tools/registry.py`); a new dependency goes in
   `ToolDeps`, `get_tool_deps` (`app/api/deps.py`) and `eval_tool_deps` (`app/evals/agent_run.py`,
   with an in-memory repository so evaluations never write to Postgres).
8. Add a unit test in `backend/tests/` calling `tool.invoke({...})` with a fake repository.
9. Say when to use it in `app/agents/prompts/assistant.md`, and add eval cases that expect it.
10. Run `/check`.
