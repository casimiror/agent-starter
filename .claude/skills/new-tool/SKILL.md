---
name: new-tool
description: Add a tool to an agent from a recipe (knowledge-search, db-write, config-link, http-api, custom), with its unit test, registry wiring, prompt mention and eval cases. Use whenever the agent needs a new capability.
argument-hint: <tool_name> <what it does>
---
# New tool

Add one tool: $ARGUMENTS

A tool is one file in `backend/app/tools/<area>/<tool_name>.py` exposing
`build_<tool_name>_tool(...) -> BaseTool`, built with `ToolBuilder`. Read
`docs/architecture/backend.md` (Tools) first.

## 1. Spec

Fill this spec before writing code. If `plan.md` (Agents and tools) already answers a field, take
it from there; ask the user only for what is missing, in one round of questions.

| Field | Question |
| --- | --- |
| Name | snake_case verb or verb_noun (`search_knowledge`, `create_ticket`) |
| Agent | which agent gets it (`assistant` unless `plan.md` lists others) |
| Does | one sentence: what it returns or changes |
| Trigger | when the agent must call it (this becomes the description the model reads) |
| Args | each argument, its type and a description; which are optional |
| Reads / writes | does it change anything (a table, an external system)? |
| Source | where the data comes from: documents, a table, an external API, settings |
| Failure | what happens when there is nothing to return or the source is down |
| Personal data | does it receive emails, names, phones? (they go only to its own table) |

## 2. Pick the recipe

| The tool... | Recipe |
| --- | --- |
| answers from documents the project curates | [knowledge-search](recipes/knowledge-search.md) |
| stores something: a lead, a ticket, an escalation, a request | [db-write](recipes/db-write.md) |
| returns fixed data from settings: a link, an email, hours | [config-link](recipes/config-link.md) |
| reads or writes an external HTTP API | [http-api](recipes/http-api.md) |
| none of the above | [custom](recipes/custom.md) |

Read the recipe file and follow it. Recipes give the files, the code shape and the tests; adapt
names and fields to the spec, and never copy placeholder text (`<...>`) into the code.

## 3. Rules every recipe follows

1. Args are a Pydantic model with a `Field(description=...)` per arg: the model reads them.
2. The description says *when* to call the tool, not only what it does.
3. Data access goes through a repository or client passed in as a dependency, never a DAO or a
   session.
4. Per-turn context (conversation id) comes from `config: RunnableConfig`, never from args.
5. Return short strings; failures start with an UPPERCASE code the prompt can react to
   (`NO_RESULTS:`, `UNAVAILABLE:`).
6. Register it in `build_<agent>_tools` (`app/tools/registry.py`). A new dependency goes in
   `ToolDeps`, in `get_tool_deps` (`app/api/deps.py`) and in `eval_tool_deps`
   (`app/evals/agent_run.py`, with an in-memory stand-in so evaluations never write to Postgres or
   call the external system).
7. A unit test in `backend/tests/test_<area>_tools.py` calling `tool.invoke({...})` with a fake
   dependency. No real LLM, no network.
8. Say when to use it in the agent's prompt (`app/agents/prompts/<agent>.md`, "How you answer").
9. Add 2-3 cases to `app/evals/dataset.jsonl` that expect it (`expected_tools`), and update the
   judge's rubric (`app/evals/prompts/judge.md`) if it adds a behaviour.
10. Update `plan.md` (Agents and tools) and `docs/architecture/backend.md` if the recipe says so.
11. `/check`, then commit on the tool's own branch (`feat/<tool-name>-tool`).
