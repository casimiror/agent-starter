from contextlib import contextmanager
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

from app.core import observability
from app.domain.models import Conversation, Message
from app.services.chat_service import ChatService


class FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class FakeLangfuse:
    def __init__(self) -> None:
        self.span = FakeSpan()
        self.started: list[dict] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.started.append(kwargs)
        yield self.span


def _record_propagation(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    @contextmanager
    def fake_propagate(**kwargs):
        calls.append(kwargs)
        yield

    monkeypatch.setattr(observability, "propagate_attributes", fake_propagate)
    return calls


def test_trace_turn_is_noop_without_langfuse(monkeypatch):
    monkeypatch.setattr(observability, "_client", None)
    with observability.trace_turn("conv", "visitor", "hi") as trace:
        assert trace.config == {"callbacks": []}
        trace.finish("reply", None)  # must not fail


def test_trace_turn_sets_user_and_session(monkeypatch):
    client = FakeLangfuse()
    monkeypatch.setattr(observability, "_client", client)
    calls = _record_propagation(monkeypatch)

    with observability.trace_turn("conv-1", "visitor-1", "hi") as trace:
        assert len(trace.config["callbacks"]) == 1
        trace.finish("hello", "price in output")

    assert calls[0]["user_id"] == "visitor-1" and calls[0]["session_id"] == "conv-1"
    assert client.started[0]["input"] == "hi"
    metadata = {"blocked_by": "price in output", "tools_called": [], "context": ""}
    expected = {"output": "hello", "metadata": metadata}
    assert client.span.updates == [expected]


class FakeConversations:
    def __init__(self) -> None:
        self.conversation = Conversation(
            id=uuid4(), visitor_id=None, created_at="2026-10-24T00:00:00Z"
        )
        self.created_with: list = []

    def get_or_create(self, conversation_id, visitor_id=None):
        self.created_with.append(visitor_id)
        return self.conversation

    def recent_messages(self, conversation_id, limit):
        return []

    def append(self, conversation_id, role, content):
        return Message(
            id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at="2026-10-24T00:00:00Z",
        )


class FakeAgent:
    def invoke(self, state, config):
        return {"messages": [*state["messages"], AIMessage("ok")], "blocked_by": None}


def test_chat_service_passes_visitor_as_langfuse_user(monkeypatch):
    monkeypatch.setattr(observability, "_client", FakeLangfuse())
    calls = _record_propagation(monkeypatch)
    conversations, visitor_id = FakeConversations(), uuid4()

    result = ChatService(conversations, FakeAgent(), 10).handle_turn(None, "hi", visitor_id)

    assert result.message_id is not None  # the stored reply, target of 👍/👎
    assert conversations.created_with == [visitor_id]
    assert calls[0]["user_id"] == str(visitor_id)
    assert calls[0]["session_id"] == str(conversations.conversation.id)


def test_stored_visitor_wins_over_request(monkeypatch):
    monkeypatch.setattr(observability, "_client", FakeLangfuse())
    calls = _record_propagation(monkeypatch)
    conversations, stored = FakeConversations(), uuid4()
    conversations.conversation.visitor_id = stored

    ChatService(conversations, FakeAgent(), 10).handle_turn(uuid4(), "hi", uuid4())

    assert calls[0]["user_id"] == str(stored)


class ToolCallingAgent:
    def invoke(self, state, config):
        call = AIMessage("", tool_calls=[{"name": "search_knowledge", "args": {}, "id": "1"}])
        result = ToolMessage(
            "[faq › Pricing]\nOn a call.", tool_call_id="1", name="search_knowledge"
        )
        return {"messages": [*state["messages"], call, result, AIMessage("ok")], "blocked_by": None}


def test_turn_span_carries_tools_and_context_for_the_online_judge(monkeypatch):
    client = FakeLangfuse()
    monkeypatch.setattr(observability, "_client", client)
    _record_propagation(monkeypatch)

    ChatService(FakeConversations(), ToolCallingAgent(), 10).handle_turn(None, "price?")

    metadata = client.span.updates[0]["metadata"]
    assert metadata["tools_called"] == ["search_knowledge"]
    assert metadata["context"] == "<search_knowledge>\n[faq › Pricing]\nOn a call."
