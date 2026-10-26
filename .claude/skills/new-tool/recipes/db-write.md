# Recipe: db-write

The tool stores something for the team to follow up: an escalation, a lead, a ticket, a request.
One table, one DAO, one repository, one tool. Read `docs/database.md` first.

Placeholders: `<thing>` singular snake_case (`escalation`), `<Thing>` its class name
(`Escalation`), `<things>` the table (`escalations`).

## Schema

### `backend/app/db/models.py`

```python
class <Thing>Row(TimestampedMixin, Base):
    """<What it is, who reads it.>"""

    __tablename__ = "<things>"
    __table_args__ = (
        CheckConstraint("status in ('open', 'done')", name="<things>_status_check"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # ...the spec's fields: Text for free text, nullable for optional args
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
```

### Migration

`make migration m="add <things>"`, then **read and tidy** the file: rename it to the next number
(`000N_<things>.py`, revision `"000N"`), match the style of `0001_initial_schema.py`, and add RLS in
the same migration:

```python
    op.execute("alter table public.<things> enable row level security")
```

`make migrate`, `make migrate-check`, `make migrate-roundtrip`. A new table is backward compatible,
so it can merge while the old code runs.

## Data layer

### `backend/app/db/daos/<thing>_dao.py`

```python
from app.db.daos.base_dao import BaseDAO
from app.db.models import <Thing>Row


class <Thing>DAO(BaseDAO[<Thing>Row]):
    model = <Thing>Row
```

### `backend/app/domain/models.py`

```python
class <Thing>(BaseModel):
    id: UUID
    conversation_id: UUID
    email: str
    # ...the same fields as the row
    created_at: datetime
```

### `backend/app/repositories/<thing>_repository.py`

```python
from uuid import UUID

from app.db.daos.<thing>_dao import <Thing>DAO
from app.domain.models import <Thing>


class <Thing>Repository:
    def __init__(self, <things>: <Thing>DAO) -> None:
        self._<things> = <things>

    def create(self, conversation_id: UUID, **fields: str | None) -> <Thing>:
        row = self._<things>.insert(conversation_id=conversation_id, **fields)
        return <Thing>.model_validate(row, from_attributes=True)
```

Prefer explicit keyword arguments over `**fields` when there are few.

## Tool: `backend/app/tools/<area>/<tool_name>.py`

```python
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, EmailStr, Field

from app.repositories.<thing>_repository import <Thing>Repository
from app.tools.builder import ToolBuilder


class <ToolName>Args(BaseModel):
    email: EmailStr = Field(description="User's email, asked for explicitly")
    question: str = Field(description="<what to store>, in the user's words")
    name: str | None = Field(default=None, description="User's name if they gave it")


def build_<tool_name>_tool(<things>: <Thing>Repository) -> BaseTool:
    def run(email: str, question: str, config: RunnableConfig, name: str | None = None) -> str:
        conversation_id = UUID(config["configurable"]["conversation_id"])
        <things>.create(conversation_id, email=email, question=question, name=name)
        return "<CODE>: <what happens next, for the agent to tell the user>."

    return (
        ToolBuilder("<tool_name>")
        .describe(
            "<What it does>. <When to call it>. Only call it after the user gave <the required "
            "details>; ask for what is missing first."
        )
        .args(<ToolName>Args)
        .handler(run)
        .build()
    )
```

`EmailStr` rejects a bad email before the handler runs; inside the graph the error goes back to
the model, which asks again.

## Wiring

- `app/tools/registry.py`: add `<things>: <Thing>Repository` to `ToolDeps` and the tool to
  `build_<agent>_tools`.
- `app/api/deps.py` `get_tool_deps`: `<Thing>Repository(<Thing>DAO(get_sessions()))`.
- `app/evals/agent_run.py` `eval_tool_deps`: `RecordingRepository()` in its place, so evaluations
  never write to Postgres.

## Tests: `backend/tests/test_<area>_tools.py`

```python
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools.<area>.<tool_name> import build_<tool_name>_tool


class Fake<Thing>s:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, conversation_id, **fields):
        self.created.append({"conversation_id": conversation_id, **fields})


ARGS = {"email": "ana@example.com", "question": "<a realistic request>"}


def _config(conversation_id) -> dict:
    return {"configurable": {"conversation_id": str(conversation_id)}}


def test_stores_the_request_for_the_conversation():
    repo, conversation_id = Fake<Thing>s(), uuid4()
    result = build_<tool_name>_tool(repo).invoke(ARGS, config=_config(conversation_id))
    assert result.startswith("<CODE>")
    assert repo.created == [{"conversation_id": conversation_id, "name": None, **ARGS}]


def test_rejects_a_bad_email():
    repo = Fake<Thing>s()
    with pytest.raises(ValidationError):
        build_<tool_name>_tool(repo).invoke({**ARGS, "email": "nope"}, config=_config(uuid4()))
    assert repo.created == []
```

## Prompt, evals, docs

- Prompt: when to call it, which details to ask for first, what to tell the user afterwards.
- Eval cases: `category: "action"` or `"escalation"`, `expected_behavior: "act"` or `"escalate"`,
  `expected_tools: ["<tool_name>"]`, with all the details in the question; and one case where a
  detail is missing (the agent must ask, `expected_tools: []`).
- Docs: the table in `docs/database.md` (Schema), and in `docs/conventions.md` (Secrets and PII)
  that this table holds personal data. Never log the args.
