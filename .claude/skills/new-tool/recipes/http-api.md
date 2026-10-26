# Recipe: http-api

The tool reads from (or writes to) an external HTTP API: order status, a CRM, a calendar, a
weather service. The API is wrapped in a small client in `app/clients/`, passed to the tool as a
dependency, so the tool never builds requests and tests never touch the network.

## Settings: `backend/app/core/config.py`

```python
    # <Service>: <what the agent uses it for>.
    <service>_base_url: str = "<https://api.example.com>"
    <service>_api_key: str = ""
    <service>_timeout: float = 10.0
```

Add them to `.env.example` and to the Vercel variables in `docs/deployment.md`. The key is a
secret: env only, never logged.

## Client: `backend/app/clients/<service>.py`

Uses `httpx` (already installed with FastAPI). One method per call the agent needs, returning
domain data (a Pydantic model or a plain dataclass), never the raw response.

```python
import logging

import httpx
from pydantic import BaseModel

log = logging.getLogger("app.clients.<service>")


class <Service>Unavailable(Exception):
    """The API failed, timed out or answered with an unexpected status."""


class <Result>(BaseModel):
    # ...only the fields the agent needs
    status: str


class <Service>Client:
    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            # Retries connection failures; HTTP errors are handled below.
            transport=httpx.HTTPTransport(retries=2),
        )

    def get_<thing>(self, <thing>_id: str) -> <Result> | None:
        """None when it doesn't exist (404)."""
        try:
            response = self._http.get(f"/<things>/{<thing>_id}")
        except httpx.HTTPError as exc:
            log.warning("<service> request failed", extra={"error": type(exc).__name__})
            raise <Service>Unavailable from exc
        if response.status_code == 404:
            return None
        if response.is_error:
            log.warning("<service> error", extra={"status": response.status_code})
            raise <Service>Unavailable
        return <Result>.model_validate(response.json())
```

Define a `Protocol` with the same methods if the tool should depend on an interface; the fake in
the tests and the stand-in for evaluations implement it.

## Tool: `backend/app/tools/<area>/<tool_name>.py`

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.clients.<service> import <Service>Client, <Service>Unavailable
from app.tools.builder import ToolBuilder


class <ToolName>Args(BaseModel):
    <thing>_id: str = Field(description="<What it is and where the user finds it>")


def build_<tool_name>_tool(client: <Service>Client) -> BaseTool:
    def run(<thing>_id: str) -> str:
        try:
            result = client.get_<thing>(<thing>_id)
        except <Service>Unavailable:
            return "UNAVAILABLE: <service> is not answering. Apologise and <fallback>."
        if result is None:
            return f"NOT_FOUND: no <thing> {<thing>_id}. Ask the user to check it."
        return f"<Sentence with the fields the agent needs: {result.status}>"

    return (
        ToolBuilder("<tool_name>")
        .describe("<What it returns>. Call it when <trigger>; ask for the <thing> id first.")
        .args(<ToolName>Args)
        .handler(run)
        .build()
    )
```

## Wiring

- `app/tools/registry.py`: add `<service>: <Service>Client` to `ToolDeps` and the tool to
  `build_<agent>_tools`.
- `app/api/deps.py` `get_tool_deps`: add `<service>=<Service>Client(...)` built from settings to
  the `ToolDeps(...)` call (keyword arguments).
- `app/evals/agent_run.py` `eval_tool_deps`: `<service>=` a stand-in client with canned answers
  for the ids the eval cases use (evaluations never call the real API). Keep it in `app/evals/`
  (e.g. `stubs.py`).

## Tests: `backend/tests/test_<area>_tools.py`

Fake client for the tool; `httpx.MockTransport` for the client itself:

```python
import httpx

from app.clients.<service> import <Service>Client, <Service>Unavailable
from app.tools.<area>.<tool_name> import build_<tool_name>_tool


class FakeClient:
    def __init__(self, result=None, down=False):
        self.result, self.down = result, down

    def get_<thing>(self, <thing>_id):
        if self.down:
            raise <Service>Unavailable
        return self.result


def test_not_found_and_unavailable_codes():
    assert build_<tool_name>_tool(FakeClient()).invoke({"<thing>_id": "1"}).startswith("NOT_FOUND")
    down = build_<tool_name>_tool(FakeClient(down=True)).invoke({"<thing>_id": "1"})
    assert down.startswith("UNAVAILABLE")


def test_client_maps_404_to_none():
    client = <Service>Client("https://api.test", "key", 1)
    client._http = httpx.Client(  # noqa: SLF001 - swap the transport for the test
        base_url="https://api.test", transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )
    assert client.get_<thing>("1") is None
```

## Prompt, evals, docs

- Prompt: when to call it, which id to ask for, what to say on `NOT_FOUND` and `UNAVAILABLE`.
- Eval cases: one per canned answer of the stand-in (found, not found, down).
- Docs: the service in `docs/architecture/backend.md` (a `Clients` row in Layers if it is the
  first one: `app/clients/`, wraps one external API, must not be imported by routes or services).
