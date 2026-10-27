# plan.md — <Project name>

<!-- Template. Fill every section before writing code; /kickoff drafts it from the brief and waits
for approval. Keep it short: one screen per section. -->

## Goal

<One paragraph: who uses the agent, what they get from it, and what "done" means (deployed URL,
budget in hours).>

## Users and the scenarios we commit to

| # | Scenario (from the brief) | How the agent handles it |
|---|---|---|
| 1 | <a question or task a user brings> | <which tool, which data, what reply> |
| 2 | | |
| n | Something it can't answer or do | <say so / escalate: where the request goes> |

## Agents and tools

| Agent | Job | Tools |
|---|---|---|
| `assistant` | <its job> | <tool names> |

| Tool | Reads or writes | Data source | When the agent calls it | Recipe |
|---|---|---|---|---|
| `<tool_name>` | reads / writes | <documents, table, API, settings> | <trigger> | knowledge-search / db-write / config-link / http-api / custom |

## Scope decisions

**In (v1)**
- <capabilities>
- Guardrails: input length cap, prompt-injection heuristics, only `ALLOWED_LINKS` in replies;
  <project-specific ones>.
- Conversation, messages and feedback in Postgres (Supabase); Langfuse tracing per turn; rate limit
  per IP on `/api/chat`.
- Channels beyond the web UI: <none (web only) / WhatsApp / voice, from the Channels section>.
  Same prompt, tools and guardrail classes on all of them; in realtime voice there is no LangGraph
  graph and the guardrails act on transcripts (`docs/channels.md`, `/new-channel`).

**Out (and why)**
- <what is deliberately not built, and the reason>

## Model choice

<Provider and model, and why (latency, cost, tool calling). Env-configurable: `LLM_PROVIDER`,
`LLM_MODEL`. Compare candidates with `make eval` before fixing the choice.>

## Channels

<Besides the web UI (always on), which channels the project serves and how. Written by
`/kickoff` and completed by `/new-channel`. For a web-only project write "Web only" and delete
the table. Options: WhatsApp (Twilio); voice `relay` (ConversationRelay, recommended), `realtime`
(speech-to-speech, OpenAI) or `gather` (plain webhooks). See `docs/channels.md`.>

| Channel | Mode | Why | Hosting needs | Open setup steps |
|---|---|---|---|---|
| web | `/api/chat` | always on | Vercel or any host | none |
| <whatsapp / voice> | <whatsapp; relay / realtime / gather> | <why this one> | <WebSockets? process that keeps running after the response?> | <Twilio console, ngrok, production webhooks, secrets> |

## Evaluation

Which dataset categories test each scenario (`backend/app/evals/dataset.jsonl`, at least one case
per scenario; see `docs/evaluation.md`):

| Scenario | Cases that test it |
|---|---|
| 1. <scenario> | <categories> |

Plus `guardrail` and `off_topic` cases, and the online judge in Langfuse on production traffic.

## Phases

1. **Kickoff** — this plan, prompt, `src/config.ts`, `ALLOWED_LINKS`. ✅ when the plan is approved.
2. **Deploy early** — Supabase, Vercel, GitHub `production` environment (`docs/deployment.md`).
3. **Tools** — one PR per tool (`/new-tool`), each with its unit test and eval cases.
4. **Evaluation** — dataset covering every scenario; `make eval` until the pass rate is acceptable.
5. **Channels** (if any) — `/new-channel`: settings, Twilio, a local test through `make tunnel`.
6. **Polish + redeploy** — README, known issues, what I'd do next.

## Risks

- <content accuracy, shared API key limits, data the agent must not see, ...>
- <channels, if any: realtime voice has weaker guardrails (they act on transcripts, a few words can
  be heard first); the per-sender lock, deduplication and limits are per process; WebSocket and
  background-task needs rule out Vercel functions; Twilio trial accounts and the WhatsApp sandbox
  limit who can test; WhatsApp has a 24-hour window and no outbound templates>

## Open questions

- <what the brief leaves open>
