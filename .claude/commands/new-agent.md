---
description: Scaffold a new LangGraph agent with AgentBuilder
argument-hint: <agent_name> <its job>
---
Create a new agent: $ARGUMENTS

1. Write the system prompt first in `backend/app/agents/prompts/<agent_name>.md`
   (role, how to answer, scope in/out, style), following `assistant.md`.
2. Add `backend/app/agents/<agent_name>_agent.py` with `build_<agent_name>_agent(llm, tools, settings)`
   using `AgentBuilder` — reuse existing guardrails unless the agent needs different ones.
3. Its tools: a `build_<agent_name>_tools(deps)` function in `app/tools/registry.py`.
4. Wire it in `app/api/deps.py` only. Routes/services must not build agents.
5. Test the graph with `GenericFakeChatModel` like `tests/test_builders.py` (no real LLM calls in unit tests).
6. Update `docs/architecture/backend.md` if routing between agents is introduced.
7. Run `/check`.
