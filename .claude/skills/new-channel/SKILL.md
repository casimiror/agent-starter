---
name: new-channel
description: Turn on WhatsApp and/or voice (phone calls) for a project created from agent-starter - ask which channels and which kind of voice, configure CHANNELS and the voice settings, fill the Channels section of plan.md and guide the Twilio and ngrok setup and the first test. Use when the project needs a channel besides the web UI.
argument-hint: <channels, e.g. "whatsapp and voice"; optional>
---
# New channel

Enable channels for this project: $ARGUMENTS

The channel code already exists in this template and is off by default (`CHANNELS=web`). This
skill decides which channels the project wants, configures them and walks the user through the
provider setup. Read `docs/channels.md` first (setup steps, variables, limits per channel and
mode), then `plan.md`, `docs/deployment.md` and `.env.example`.

**The agent and its prompt are not changed per channel.** Same graph, same prompt, same tools, same
guardrails everywhere. The only per-channel text is the voice greeting and link phrase. If a
channel seems to need a different answer style, fix the shared prompt or say it is a limit; never
fork the agent. Do not change backend behaviour in this skill.

**Never ask the user to paste a secret in the chat** and never echo one. They put secrets in `.env`
(and in the host's dashboard for production) themselves.

## 0. Preconditions

- `git status` is clean and you are on a branch for this task, `feat/<channel>-channel-setup`
  (e.g. `feat/whatsapp-channel-setup`), from `main`. Never commit to `main`.
- `.env` exists (`make env`). If not, run `make env`.
- `plan.md` is filled (run `/kickoff` first for a new project). If it is still the template, ask
  whether to continue anyway; the Channels section needs the project's language and tone.

## 1. Ask (AskUserQuestion, recommended option first)

Only ask what `plan.md` and `$ARGUMENTS` leave open.

1. **Which channels?** (multiSelect) WhatsApp, Voice. The web UI is always on.
2. If Voice, **"Which kind of voice?"**:
   1. **ConversationRelay (Recommended)**: `VOICE_MODE=relay`. Near real time with interruptions;
      Twilio does the speech, our same agent answers text, so the same prompt and guardrails apply
      and any text LLM works, Claude included. Needs a host that keeps WebSockets open.
   2. **Speech-to-speech realtime**: `VOICE_MODE=realtime`. The most natural. OpenAI Realtime only
      (Claude has no audio models). Guardrails act on transcripts, so a few words can be heard
      before a block takes effect. About US$0.10 per minute with `gpt-realtime-2.1` (the mini is
      cheaper). Needs a WebSocket host and `OPENAI_API_KEY`.
   3. **Basic Gather**: `VOICE_MODE=gather`. The simplest: plain webhooks, works on Vercel. Noticeable
      pauses between turns and a ~15 s limit per turn (a turn with several tool calls can exceed it).
3. If realtime: **model**, `gpt-realtime-2.1` (Recommended) or `gpt-realtime-2.1-mini`.
4. If Voice: the **voice language** (BCP 47, e.g. `es-MX`, `en-US`) if `plan.md` does not give it.
   For relay, also the TTS/transcription providers only if the defaults (`ElevenLabs`, `Deepgram`)
   do not cover the language; the voice must exist for that provider and language.

## 2. Check hosting

Read `plan.md` (Model choice, Scope) and `docs/deployment.md` for where the project runs.

- `relay` or `realtime` on **Vercel**: warn that Vercel functions do not keep WebSockets open, so
  the call would fail. Offer `gather`, or a container host (the Docker image on a VM, Fly.io,
  Railway, Render...) for the voice routes. Record the decision.
- **WhatsApp on Vercel**: replies are sent from a background task after the response, which Vercel
  does not guarantee to run. Tell the user it needs a host where the process keeps running
  (`docs/channels.md` > WhatsApp > Limits), or accept that replies may be lost; record it.
- Local development always works: `make tunnel` runs the app in Docker.

## 3. Configure

Write these in `.env` (yourself, they are not secrets) and, where they are project decisions, as
the new defaults in `.env.example`:

- `CHANNELS` (e.g. `web,whatsapp,voice`).
- Voice: `VOICE_MODE`, `VOICE_LANGUAGE`, and `VOICE_GREETING` and `VOICE_LINK_PHRASE` written in the
  project's language and tone (take them from `plan.md` and `backend/app/agents/prompts/
  assistant.md`; the greeting is the first thing the caller hears, the link phrase replaces any URL,
  e.g. "You'll find the link in our chat or on our website."). Relay: `VOICE_TTS_PROVIDER`,
  `VOICE_VOICE`, `VOICE_TRANSCRIPTION_PROVIDER` if not the defaults. Realtime: `VOICE_REALTIME_MODEL`.
  Adjust `RATE_LIMIT_WHATSAPP`, `RATE_LIMIT_VOICE` and `VOICE_MAX_CALL_SECONDS` only if `plan.md`
  asks for it.

The user fills in, in `.env`, the values you must not see: `CHANNEL_ID_SECRET` (they generate it
with `openssl rand -hex 32`), `TWILIO_ACCOUNT_SID` (WhatsApp only) and
`TWILIO_AUTH_TOKEN`, `OPENAI_API_KEY` (realtime), `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` (their free
static domain, no `https://`) and `PUBLIC_BASE_URL` (`https://<NGROK_DOMAIN>` locally). Check they
are set without printing them (`grep -c '^NAME=.' .env`). The app refuses to start naming what is
missing, which is the final check.

Tell them that **`CHANNEL_ID_SECRET` must never change once in use**: rotating it gives every
sender a new anonymous id and detaches all their history.

## 4. Fill the Channels section of `plan.md`

One row per enabled channel (see the template): mode, why it was chosen, hosting needs, and the
setup steps still open (Twilio console, ngrok, production webhooks). Update Scope (in/out) and
Risks with the real consequences of the choice (weaker guardrails in realtime, per-process state,
trial-account limits, WhatsApp 24-hour window and no templates). No placeholder may remain.

## 5. Guide the local test

Do the steps you can, and tell the user exactly what to do in the Twilio console.

1. `make tunnel` (db, api with reload, web and ngrok). `make dev` and `make up` do **not** start
   ngrok; only `make tunnel` does.
2. `curl -s <PUBLIC_BASE_URL>/api/health` must answer 200 through the tunnel.
3. Twilio console (user). Use `<PUBLIC_BASE_URL>` exactly as in `.env`:

   | Channel | Where | Value |
   | --- | --- | --- |
   | WhatsApp | Messaging > Try it out > Send a WhatsApp message > Sandbox settings > **When a message comes in** | `<PUBLIC_BASE_URL>/api/channels/whatsapp/webhook`, POST. Each phone first sends the sandbox `join <two-words>` message |
   | Voice (all modes) | Phone Numbers > the number > **A call comes in** | Webhook, `<PUBLIC_BASE_URL>/api/channels/voice/incoming`, HTTP POST |

   - `relay` only: Voice > Settings (or General) > accept the "Predictive and Generative AI/ML
     Features Addendum"; ConversationRelay requires it.
   - A **trial** account can only call and message verified numbers: verify the tester's phone in
     the console first.
   - `gather` and `realtime` need no addendum. Realtime needs `OPENAI_API_KEY` in `.env`.
4. Open the ngrok inspector at http://localhost:4040: every request Twilio sent, with **Replay**
   (a replayed WhatsApp `MessageSid` is dropped as a duplicate; edit it first).
5. Manual test script, on each channel:
   - A knowledge question the project answers (right content, no invented data).
   - A booking or escalation that triggers a tool.
   - A price question the project blocks (`NoInventedPricesGuardrail`).
   - A prompt-injection attempt ("ignore your instructions and ..."): refused.
   - WhatsApp: send a photo or a voice note: the canned "I can only read text messages" reply.
   - Voice: interrupt the reply by talking over it; and listen for the link phrase where a reply
     would have had a URL.
   - A follow-up in the same conversation ("and what about the second one?"): WhatsApp keeps the
     conversation for 24 h; each call is one conversation.
   - In Langfuse: the trace carries the tag `channel:whatsapp` or `channel:voice` and a UUID as the
     user, never a phone number. In the `messages` table the conversation has that `channel`.
6. Troubleshooting:
   - **Twilio gets 404**: the tunnel is not running (ngrok answers 404 itself when its endpoint is
     offline; run `make tunnel`) or the console URL path is wrong (check against the table above).
   - **403**: the signature did not verify. The URL Twilio signed differs from `PUBLIC_BASE_URL` +
     path: check the scheme (`https`), the domain, no trailing slash in `PUBLIC_BASE_URL`, and that
     `TWILIO_AUTH_TOKEN` is the account's current token.
   - **Voice WebSocket closes with 1008**: the handshake signature failed; same cause as the 403,
     for the `wss://` URL. Check `PUBLIC_BASE_URL`.
   - **Silence or an error message after the greeting** (relay): the AI/ML addendum is not accepted,
     or the TTS voice does not exist for that provider and language.
   - **No reply on WhatsApp but the webhook answered 200**: the sandbox join expired (72 h), the
     phone never joined, or the REST send failed (look for the Twilio error code in the logs).
   - **The app does not start**: it names the missing variable (`Settings.check_channels`).
   - **Nothing happens after `make dev` or `make up`**: they do not start ngrok; use `make tunnel`.

## 6. Finish

`make check`, commit in small steps (`.env.example` and defaults; `plan.md`), open the PR with
`gh pr create` and merge when CI passes. `.env` is never committed. Then report: channels and mode
enabled, the hosting decision, what the user still has to do themselves (secrets, Twilio console,
production webhooks via `/deploy-setup`), and anything the test showed that needs a fix.
