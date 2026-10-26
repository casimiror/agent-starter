from langgraph.graph import MessagesState


class AgentState(MessagesState):
    # Set by a guardrail node; short-circuits the graph and records why in Langfuse.
    blocked_by: str | None
