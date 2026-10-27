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
- Optional channels beyond the web UI, off by default (`CHANNELS`, `docs/channels.md`): WhatsApp
  through Twilio (text only, replies sent through the REST API from a background task, so it needs
  a host where the process keeps running; sandbox or an approved sender, no outbound templates);
  phone calls through Twilio (`VOICE_MODE=relay` ConversationRelay, which needs WebSockets, or
  `gather`, plain webhooks bound by Twilio's ~15 s timeout; Twilio does the speech, one
  conversation per call, links never read aloud).
  Delete this line if the project only has the web UI.

**Out (and why)**
- <what is deliberately not built, and the reason>

## Model choice

<Provider and model, and why (latency, cost, tool calling). Env-configurable: `LLM_PROVIDER`,
`LLM_MODEL`. Compare candidates with `make eval` before fixing the choice.>

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
5. **Polish + redeploy** — README, known issues, what I'd do next.

## Risks

- <content accuracy, shared API key limits, data the agent must not see, ...>

## Open questions

- <what the brief leaves open>
