---
name: deploy-setup
description: Set up or check the production deploy of a project created from agent-starter - GitHub production environment, Supabase, Vercel, enabled channels (host and Twilio webhooks), Langfuse and its online judge - doing the safe steps and guiding the user through the ones that need their secrets or accounts.
---
# Deploy setup

Take this repo to production on Vercel + Supabase, following `docs/deployment.md` (read it
first). Do the steps that need no secret; for the rest, tell the user exactly what to do and
check the result. **Never ask the user to paste a secret in the chat** and never echo one: they
type secrets into the dashboards or into `gh secret set` themselves.

Check each step's state first and skip what is already done.

## 1. GitHub `production` environment

- Check: `gh api repos/{owner}/{repo}/environments/production` (404 means missing).
- Create it, limited to `main` (you may run this):

  ```bash
  gh api -X PUT repos/{owner}/{repo}/environments/production \
    -F "deployment_branch_policy[protected_branches]=false" \
    -F "deployment_branch_policy[custom_branch_policies]=true"
  gh api -X POST repos/{owner}/{repo}/environments/production/deployment-branch-policies \
    -f name=main -f type=branch
  ```

## 2. Supabase (the user)

Tell the user to:
1. Create a project in a region close to the Vercel functions (e.g. `us-east-1` with `iad1`).
2. From **Connect**, copy the **transaction pooler** URL (port 6543, for Vercel) and the **session
   pooler** URL (port 5432, for migrations), with the password filled in.
3. Run `! gh secret set SUPABASE_DB_URL --env production` and paste the session pooler URL when
   asked, and put the same URL in `.env` as `SUPABASE_DB_URL` for manual runs.

Then check: `gh secret list --env production` shows `SUPABASE_DB_URL`. Run `make migrate-supabase`
(it reads `.env`) and confirm `alembic current` is at head. From now on merges migrate it.

## 3. Vercel (the user)

Tell the user to import the repo (**Add New → Project**) with Root Directory `backend` and no
Build Command override, set the region to Supabase's, and add the variables of
`docs/deployment.md` (Setup: 2. Vercel) for **Production**: `DATABASE_URL` (transaction pooler),
`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `APP_NAME`, `ALLOWED_LINKS`, Langfuse keys, and the
optional `LLM_FALLBACKS`, `RATE_LIMIT_STORAGE_URI`. Never `EVAL_ENABLED`.

**Preview** must not use the production database: either a second Supabase project for previews
(its pooler URL as Preview `DATABASE_URL`) or no `DATABASE_URL` in Preview (previews then fail on
chat; say which the user chose in `docs/deployment.md`).

Then check, once they give you the URL (or `gh api repos/{owner}/{repo}/deployments`):

```bash
curl -sD - https://<project>.vercel.app/api/health          # 200
curl -s -X POST https://<project>.vercel.app/api/chat \
  -H 'content-type: application/json' -d '{"message":"What can you help me with?"}'
```

The reply must match the prompt's scope, and the response must carry `x-request-id`. Put the
production URL in `README.md` (Live) and `docs/deployment.md`.

## 4. Channels (only if `CHANNELS` or `plan.md` has WhatsApp or voice)

Read `plan.md` (Channels) and `docs/channels.md` (Limits). Check the host against the modes:

- Voice `relay` or `realtime` keeps WebSockets open for the whole call, and WhatsApp sends its
  reply from a background task after answering the webhook. **Vercel functions do neither
  reliably.** If the project deploys to Vercel, warn the user and offer: voice `gather` (plain
  webhooks; still bound by Twilio's ~15 s per turn), or a container host (the Docker image on a
  VM, Fly.io, Railway, Render...) for the app. Record the decision in `plan.md` (Channels) and
  `docs/deployment.md`. Do not put a mode that cannot work into production.
- Per-process state (deduplication, the per-visitor lock, `memory://` rate limits) is looser with
  several instances; a Redis `RATE_LIMIT_STORAGE_URI` makes the limits global.

Production variables on the host (the user sets them; never ask for the values in chat):
`CHANNELS`, `CHANNEL_ID_SECRET` (a new one from `openssl rand -hex 32`, not the development one,
and never rotated afterwards), `PUBLIC_BASE_URL` (the production https origin, no trailing slash),
`TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID` (WhatsApp), `OPENAI_API_KEY` (realtime), the `VOICE_*`
settings. No ngrok variables in production.

Twilio for production (the user, in the console): point the webhooks to the production domain, not
the ngrok one:

- WhatsApp sender (or sandbox) **When a message comes in**:
  `<PUBLIC_BASE_URL>/api/channels/whatsapp/webhook`, POST.
- Voice number **A call comes in**: `<PUBLIC_BASE_URL>/api/channels/voice/incoming`, HTTP POST.
  `relay` also needs the AI/ML addendum accepted.
- A trial account only reaches verified numbers; the WhatsApp sandbox is for testing (a real sender
  needs Meta approval).

Check: `curl -sD - <PUBLIC_BASE_URL>/api/health` is 200, then one real message or call and its
trace in Langfuse tagged `channel:<name>`. A 403 from Twilio means the signature URL differs from
`PUBLIC_BASE_URL` + path.

## 5. Langfuse (the user)

- With the keys set, a chat message creates a `chat-turn` trace in environment `production`.
- Online judge: walk the user through `docs/evaluation.md` → "Online evaluation in Langfuse" (LLM
  connection with OpenRouter, the two evaluators with the prompts from
  `backend/app/evals/prompts/online_*.md`, the mapping: `tools` → Metadata `$.tools_called`,
  `context` → Metadata `$.context`, filter `chat-turn` + `production`, sampling). If they share a
  screenshot of the mapping, check it against that section.

## 6. Report

What is live (URL), what was checked, the channels and their Twilio webhooks, and what is pending
with who has to do it.
