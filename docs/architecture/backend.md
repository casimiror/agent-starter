# Backend architecture

FastAPI app in `backend/app/`. One process serves the API (`/api/*`) and the built React app
(`app.frontend()`, registered last in `app/main.py`).
`app.frontend(..., check_dir="auto")` only skips the "build exists" check when
`FASTAPI_ENV=development` (set by `fastapi dev`); scripts that import `app.main` need the UI built
or that variable set.

## Layers

The layering is the rule. A layer only calls the one below it.

```
api/routes  ->  services  ->  repositories  ->  db/daos  ->  Postgres
                   |
                   +-> agents (LangGraph graph built by AgentBuilder)
                          +-> tools (built by ToolBuilder; may use repositories)
                          +-> guardrails (input/output nodes in the graph)
```

| Layer | Folder | Responsibility | Must not |
| --- | --- | --- | --- |
| Routes | `app/api/routes/` | HTTP and WebSocket only: validate with `app/schemas`, rate limit, call a service | contain business logic or touch the DB |
| Schemas | `app/schemas/` | Pydantic request/response models (the HTTP contract) | be used below the route layer |
| Services | `app/services/` | One use case each (`ChatService.handle_turn`): load history, invoke the graph, persist | build agents or open sessions |
| Repositories | `app/repositories/` | Domain persistence API; combine DAOs; return `app/domain` models | return ORM rows |
| DAOs | `app/db/daos/` | One class per table, subclass `BaseDAO[Row]`, each call is its own short transaction | be imported outside repositories |
| Domain | `app/domain/` | Pydantic models the app passes around | know about SQLAlchemy |
| Agents | `app/agents/` | `AgentBuilder` composes LLM + prompt + tools + guardrails into a `StateGraph` | inline prompts (they live in `app/agents/prompts/*.md`) |
| Clients | `app/clients/` | Wrappers of an external API a service calls (`WhatsAppSender` over Twilio's REST API); injected through `deps.py`, they never raise into the caller | hold business rules or be imported by routes |
| Tools | `app/tools/<area>/` | One file per tool, `build_<name>_tool(deps) -> BaseTool` via `ToolBuilder`; registered in `app/tools/registry.py` | use DAOs or sessions directly |
| Guardrails | `app/guardrails/` | Pure checks on input/output text; unit-tested | call an LLM (unless stated) |
| Core | `app/core/` | Settings, LLM factory, rate limiter, observability | depend on routes or services |

Wiring of concrete classes happens **only** in `app/api/deps.py`.

## HTTP API

| Method and path | Body | Response |
| --- | --- | --- |
| `GET /api/health` | | `{"status": "ok"}` |
| `POST /api/chat` | `message`, `conversation_id?`, `visitor_id?` | `conversation_id`, `message_id` (the stored reply), `reply` |
| `PUT /api/messages/{id}/feedback` | `{"rating": "up" \| "down"}` | 204; 404 if `id` isn't an assistant message |
| `DELETE /api/messages/{id}/feedback` | | 204 (idempotent); 404 as above |
| `POST /api/channels/whatsapp/webhook` | Twilio form (`From`, `To`, `Body`, `MessageSid`, `NumMedia`); only with `whatsapp` in `CHANNELS` | `200` and an empty `<Response/>`; `403` bad signature, `400` missing `From`/`MessageSid`, `413` body over 64 KB |
| `POST /api/channels/voice/incoming` | Twilio form (`CallSid`, `From`, ...); only with `voice` in `CHANNELS` | TwiML by `VOICE_MODE` (`<Connect><ConversationRelay>` or `<Gather>`), or `<Say>` + `<Hangup/>` over the caller limit; `403`, `400` (no `CallSid`), `413` |
| `WS /api/channels/voice/relay/ws` | Twilio ConversationRelay JSON (`setup`, `prompt`, `interrupt`, `dtmf`, `error`); `VOICE_MODE=relay` | `{"type":"text","token","last":true}` per turn, `{"type":"end"}` at the time limit; handshake with a bad signature closed with 1008 |
| `POST /api/channels/voice/relay/action` | Twilio form (`CallSid`, `SessionStatus`, `ErrorCode`, ...); `relay` | `<Response><Hangup/></Response>`; `403`, `413` |
| `POST /api/channels/voice/gather?c=<conversation_id>[&r=1]` | Twilio form (`SpeechResult`, `CallSid`); `VOICE_MODE=gather` | `<Gather><Say>reply</Say></Gather>`, or `<Say>` + `<Hangup/>`; `403`, `413` |

Limits: `RATE_LIMIT_CHAT` (10/min) and `RATE_LIMIT_FEEDBACK` (30/min) per client IP, counted in
`RATE_LIMIT_STORAGE_URI` (`memory://` per process by default; a Redis URL makes it global across
Vercel instances). Every `/api/*` response carries an `x-request-id` header (see Logging).

`/api/evals/*` exists only with `EVAL_ENABLED=true` (local): see `docs/evaluation.md`.

`/api/chat` is the web channel and is always mounted. The routers of other channels (WhatsApp,
voice) are mounted only when `CHANNELS` enables them, through the registry in
`app/api/routes/channels/__init__.py`: see `docs/channels.md`.

## A chat turn

1. `POST /api/chat` (`routes/chat.py`): slowapi limits per client IP, `ChatRequest` validates
   (`message`, optional `conversation_id`, optional `visitor_id` UUID).
2. `ChatService.handle_turn` gets or creates the conversation (storing `visitor_id` and `channel`,
   `web` unless a channel passes its own), loads the last `MAX_HISTORY_MESSAGES` from `messages`
   (the source of truth, no LangGraph checkpointer).
3. `observability.trace_turn` opens one Langfuse trace: root span + `propagate_attributes`
   (`session_id = conversation_id`, `user_id = visitor_id`, tag `channel:<name>`). The channel is
   never passed to the graph: the agent behaves the same on every channel.
4. The graph runs: `input_guard -> agent <-> tools -> output_guard`.
   - Input guardrails: max length, prompt-injection heuristics. Blocked -> canned reply, no LLM call.
   - Agent: LLM with tools bound; loops through `ToolNode` until it answers. A failing model falls
     back to the next one (see Resilience).
   - Output guardrails: only allowed URLs. Blocked -> the reply is replaced.
5. User and assistant messages are persisted **after** the turn succeeds (no half turns); the
   assistant message's id is returned as `message_id` so the UI can attach feedback to it. One
   `chat turn` log line records tools, guardrail, model and latency (never the text).
6. The route schedules `observability.flush` as a background task (serverless instances can freeze).

Graph diagram and how to modify or create agents: [`backend/app/agents/README.md`](../../backend/app/agents/README.md).

## Channels

`ChannelConversations` (`app/services/channel_conversations.py`) is the part every non-web channel
shares: an anonymous keyed-hash `visitor_id` per sender, the conversation to continue (latest on
the channel while inside `CONVERSATION_WINDOW_HOURS`) and a per-visitor lock. `hit_sender` in
`app/core/rate_limit.py` limits per sender on the limiter's storage. Both are wired or used by the
channel routers; details and the PII rule in `docs/channels.md`.

### WhatsApp turn

Unlike `/api/chat`, the HTTP response does not carry the reply: Twilio gives a webhook ~15 s.

1. `routes/channels/whatsapp.py`: 64 KB body cap (413), `X-Twilio-Signature` checked against
   `PUBLIC_BASE_URL` (403), `From`/`MessageSid` required (400), repeated `MessageSid` dropped
   (`core/dedupe.py`, per process), then `200` with an empty `<Response/>` and a `BackgroundTasks`
   task.
2. `WhatsAppService.handle_message` (background, never raises): `visitor_id` from `From`,
   `hit_sender(RATE_LIMIT_WHATSAPP, "whatsapp", visitor_id)`, canned reply for media or empty
   text, then under `ChannelConversations.lock`: `resolve` and
   `ChatService.handle_turn(..., channel="whatsapp")`. A failing turn sends an apology.
3. The reply goes through `format_for_whatsapp` (links, bold, headings, split into at most three
   messages of 1600 characters; never alters a URL) and `WhatsAppSender.send` (Twilio REST API),
   from the number the user wrote to. `observability.flush` runs at the end.

Logs hold `visitor_id`, `message_sid`, Twilio error codes and exception types: never `From`,
`To`, the text or the reply.

### A voice turn

Every Twilio route first goes through `app/api/twilio_security.py`: a 64 KB body cap and the
signature check against `PUBLIC_BASE_URL` (for the WebSocket handshake, the `wss://` URL with or
without a trailing slash). `VoiceService` (`app/services/voice_service.py`) is what the modes share:

1. `POST /api/channels/voice/incoming` -> `VoiceService.start_call(From, CallSid)`:
   `hit_sender(RATE_LIMIT_VOICE, "voice", visitor_id)`, then `ChannelConversations.start`, a **new**
   conversation per call (no 24 h reuse). The TwiML comes from `INCOMING[VOICE_MODE]`
   (`app/services/voice_twiml.py`); it holds only `visitor_id` and `conversation_id`.
2. A turn is `VoiceService.answer(call, text)`: `ChatService.handle_turn(..., channel="voice")`,
   then `format_for_speech` (after the output guardrails: strips Markdown, removes every URL and
   says `VOICE_LINK_PHRASE` once instead), flush of observability. It never raises: a failed turn
   is a spoken apology. It blocks, so routes call it in a threadpool.
3. `relay`: `RelaySession` (`app/services/voice_relay.py`) handles Twilio's WebSocket messages with
   no socket code: `setup` binds the session to the conversation (looked up with
   `ChannelConversations.find`, which also checks the channel), a final `prompt` runs a turn under
   a per-call lock and yields one `text` message, `interrupt`/`dtmf`/`error` are logged, and past
   `VOICE_MAX_CALL_SECONDS` it yields `end`. The route owns the socket and runs a prompt as a task
   so interrupts are still read during a turn.
4. `gather`: `POST /api/channels/voice/gather?c=<id>` runs the turn inside the webhook and answers
   with the reply and another `<Gather>`; empty speech is re-prompted once, then the call ends.

Adding a mode (PR "realtime"): a value in `Settings.voice_mode`, a builder in `INCOMING`, a router
gated with `only("<mode>")` included in `voice.py`.

Logs hold `visitor_id`, `conversation_id`, `call_sid`, Twilio error codes and exception types: never
`From`, `callerName`, the transcript, DTMF digits or the reply.

## Tools

Each project adds its own tools with `/new-tool`, which builds
each one from a recipe in `.claude/skills/new-tool/recipes/` (`knowledge-search`, `db-write`,
`config-link`, `http-api`, `custom`); `/kickoff` decides the tools per agent with you. A tool is one
file in `app/tools/<area>/`, `build_<name>_tool(deps) -> BaseTool` built with `ToolBuilder`, and is
registered in `build_assistant_tools` (`app/tools/registry.py`). What it needs (repositories,
clients, settings) goes in `ToolDeps`, wired in `app/api/deps.py` (`get_tool_deps`) and, for
evaluations, in `app/evals/agent_run.py` (`eval_tool_deps`, with in-memory repositories).

Conventions for tools (also in `/new-tool`): the description says *when* to call it; args are a
Pydantic model with a `Field(description=...)` each; per-turn context (conversation id) comes from
`config: RunnableConfig`, never from args; failures return a short string starting with an
UPPERCASE code (`NO_RESULTS:`, `UNAVAILABLE:`) the prompt can react to.

A knowledge tool (answering from documents) is named `search_knowledge` and renders its results
with `render_docs` (`app/domain/retrieval.py`); `build_retriever` in the registry returns its
search, which turns on the RAG evaluation (`docs/evaluation.md`).

## Guardrails

Each guardrail has `name` and `check(text) -> GuardrailResult` (`app/guardrails/base.py`).

| Guardrail | Stage | Blocks | Wired by default |
| --- | --- | --- | --- |
| `MaxLengthGuardrail` | input | messages over `MAX_INPUT_CHARS` | yes |
| `PromptInjectionGuardrail` | input | "ignore previous instructions", "reveal your system prompt", ... | yes |
| `AllowedLinksGuardrail` | output | any URL not starting with an `ALLOWED_LINKS` prefix | yes |
| `NoInventedPricesGuardrail` | output | `$`, `USD`, `€` followed by a number | no: add it when the agent must never quote prices |

The output check runs after generation, so replies are returned whole (no token streaming).

## Feedback

`FeedbackService` (`app/services/feedback_service.py`) lets a visitor rate a reply: one row per
message in `message_feedback`, upserted in one statement (`MessageFeedbackDAO.upsert`), deleted when
the vote is removed. Only assistant messages are rateable (`MessageNotRateableError` -> 404). Join
`message_feedback -> messages -> conversations` to analyse a conversation with its votes.

## Configuration

`app/core/config.py` (`Settings`, pydantic-settings). Everything comes from env; `.env.example`
documents each variable. Notable aliases: `DATABASE_URL` falls back to `POSTGRES_URL` (Vercel's
Supabase integration), `LANGFUSE_BASE_URL` to `LANGFUSE_HOST`, and `VERCEL=1` sets `serverless`.
`CHANNELS`, `CHANNEL_ID_SECRET`, `PUBLIC_BASE_URL` and `CONVERSATION_WINDOW_HOURS` configure the
channels beyond the web UI; `create_app` fails at startup on an unknown channel or a missing
secret/base URL (`docs/channels.md`). With `whatsapp` enabled, `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN` are required too, and `RATE_LIMIT_WHATSAPP` (10/minute) limits per sender.
With `voice` enabled `TWILIO_AUTH_TOKEN` is required; `VOICE_MODE` (`relay` or `gather`; anything
else stops the app at startup), `VOICE_LANGUAGE`, `VOICE_GREETING`, `VOICE_LINK_PHRASE`,
`RATE_LIMIT_VOICE` (5/minute per caller), `VOICE_MAX_CALL_SECONDS` and, for `relay`,
`VOICE_TTS_PROVIDER`, `VOICE_VOICE` and `VOICE_TRANSCRIPTION_PROVIDER` configure it.
`APP_NAME` names the API and the Langfuse evaluation dataset; `ALLOWED_LINKS` lists the URL
prefixes the agent may write.

## Resilience

`app/core/llm.py` builds every model with `LLM_TIMEOUT` and `LLM_MAX_RETRIES`: the provider client
itself retries timeouts, 429 and 5xx with exponential backoff. If the model still fails, the agent
tries `LLM_FALLBACKS` in order (`build_chat_models`; `AgentBuilder.with_fallbacks` binds the tools to
each one, so a fallback can call them too). A fallback on the same provider reuses `LLM_API_KEY`;
on another provider it needs that provider's key (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`), checked at startup. The model that answered goes to the `chat-turn` span
(`model`) and the log line; a turn answered by a fallback is logged as a warning (`fallback: true`).

## Logging

`app/core/logging.py`, configured in `create_app`: stdout, one JSON object per line
(`LOG_FORMAT=json`, what Vercel collects) or readable text locally (`LOG_FORMAT=text`).

- Log with `logging.getLogger("app.<area>")` and fields in `extra`, never values formatted into the
  message: `log.info("chat turn", extra={"latency_ms": 812})`.
- `app/api/middleware.py` (`access_log`) gives each `/api/*` request an id (the caller's
  `x-request-id` or a new one), adds it to every log line of that request, returns it in the
  `x-request-id` header and logs method, path, status and duration (warning from 400 up).
  Unhandled exceptions are logged with their traceback.
- **No PII**: never log user text, replies or tool arguments; emails are masked (`[email]`) as a
  last line of defence.
- Noisy libraries (`httpx`, `openai`, `anthropic`, `uvicorn.access`) are raised to WARNING.

## Observability

Langfuse, one trace per turn (`app/core/observability.py`). The `Langfuse(...)` client is created
once in the lifespan; `CallbackHandler()` reuses it. The root span `chat-turn` records the user
text, the reply and, as metadata, `blocked_by`, `tools_called` and `context` (the turn's tool
results), which the online judge in Langfuse reads (`docs/evaluation.md`). Traces carry the
Langfuse environment `LANGFUSE_TRACING_ENVIRONMENT`, or Vercel's `VERCEL_ENV` (`production`,
`preview`), else `development`. `visitor_id` is an anonymous UUID: never send emails or names to
Langfuse.
