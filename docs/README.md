# Documentation

| Document | Read it when you... |
| --- | --- |
| [architecture/backend.md](architecture/backend.md) | touch `backend/app/`: layers, a chat turn end to end, tools, guardrails, config, observability |
| [channels.md](channels.md) | add or enable a channel besides the web UI: shared identity and conversation pieces, per-sender limits, local ngrok tunnel, WhatsApp (Twilio) setup |
| [architecture/frontend.md](architecture/frontend.md) | touch `frontend/src/`: feature folders, component/hook/client layers, storage |
| [design/frontend.md](design/frontend.md) | change how the UI looks or behaves: tokens, class naming, components, accessibility |
| [database.md](database.md) | change the schema or connection handling: tables, migrations, RLS, local vs Supabase |
| [evaluation.md](evaluation.md) | evaluate the agent: dataset, `make eval`, metrics, judge, Langfuse experiments, online judge |
| [deployment.md](deployment.md) | deploy or debug production: Vercel, Supabase, env vars, verification |
| [conventions.md](conventions.md) | write code or commits: git workflow, naming, tests, secrets |

Scope, phases and what is out of scope: [`plan.md`](../plan.md). How to run things: the
[README](../README.md) and `make help`.

Keep these documents current in the same commit as the change they describe.
