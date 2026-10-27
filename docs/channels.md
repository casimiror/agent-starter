# Channels

A **channel** is a way to reach the same agent besides the web UI: WhatsApp, voice. The agent,
its prompt, tools and guardrails are identical on every channel; a channel only brings messages
in, takes the reply out and says which conversation they belong to. The code of each channel lives
in this template and is tested in CI, but every channel is **off by default** and enabled by
configuration.

Status: the shared foundation and the WhatsApp channel are in place; the voice channel comes in a
later change.

## Enabling a channel

```bash
CHANNELS=web,whatsapp        # web, whatsapp, voice; web (/api/chat) is always on
CHANNEL_ID_SECRET=<openssl rand -hex 32>
PUBLIC_BASE_URL=https://<your public domain>   # locally: https://<NGROK_DOMAIN>
CONVERSATION_WINDOW_HOURS=24
```

- An unknown name in `CHANNELS` stops the app at startup.
- Any channel besides `web` also needs `CHANNEL_ID_SECRET` and `PUBLIC_BASE_URL`; if either is
  empty the app refuses to start with a message naming it (`Settings.check_channels`, called in
  `create_app`), instead of failing on the first message.
- `PUBLIC_BASE_URL` is the public https origin used to build the webhook URLs a provider is told
  to call.
- Channel routers are mounted through a registry (`app/api/routes/channels/__init__.py`,
  `CHANNEL_ROUTERS`: channel name -> function that imports its router). Only enabled channels are
  imported, before `app.frontend()`. A new channel adds one line there.

## The shared pieces

Every non-web channel does the same three things before calling `ChatService.handle_turn(...,
channel=<name>)`, so they live once, in `ChannelConversations`
(`app/services/channel_conversations.py`, no HTTP code):

| Piece | What it does |
| --- | --- |
| `visitor_id(sender)` | Anonymous UUID for a phone number or call id |
| `resolve(visitor_id, channel)` | The conversation to continue, or a new one |
| `lock(visitor_id)` | Context manager held around `resolve` + the turn |

Wiring: `get_channel_conversations()` in `app/api/deps.py`.

### Identity and PII

The sender is personal data; the system never stores or logs it. `visitor_id` is
`uuid5(namespace, HMAC-SHA256(CHANNEL_ID_SECRET, sender))`: stable for the same sender, it holds no
part of the number, and it cannot be recomputed without the secret. That UUID is the
`conversations.visitor_id`, the Langfuse `user_id` and the key of the per-sender rate limit.

**Rotating `CHANNEL_ID_SECRET` gives every sender a new id**, so each one starts a fresh history
and the old conversations can no longer be linked to them. Treat the secret like a database
password and rotate it only on purpose.

### Conversation window

A sender's latest conversation on a channel is reused while its last activity (the last message,
or its creation if it has none) is newer than `CONVERSATION_WINDOW_HOURS` (default 24). After that
silence the next message opens a new conversation, so history sent to the model stays short and
on topic. The latest conversation is found with the (`visitor_id`, `channel`, `created_at`) index.

### The per-visitor lock

Two messages from one sender in quick succession would both find no fresh conversation and open
two. Callers wrap `resolve` and the turn in `with channels.lock(visitor_id):`; the same visitor
waits, different visitors do not block each other.

**Limitation:** it is a `threading.Lock` per key, so it works within one process only. With several
workers or several Vercel instances two messages can still race. Closing that needs a database
lock (a Postgres advisory lock on the visitor id) or a unique open-conversation row per sender;
the cost of the race is a duplicated, otherwise normal conversation.

### Per-sender rate limit

`hit_sender(limit, channel, key)` in `app/core/rate_limit.py` counts one message per (channel,
`visitor_id`) in the same storage as the per-IP limits (`RATE_LIMIT_STORAGE_URI`: per process with
`memory://`, global with Redis) and returns `False` once the sender is over `limit` (`"20/minute"`).
Webhooks come from the provider's addresses, so the per-IP limit cannot tell senders apart; this
one can. It follows the limiter's `enabled` flag.

### Channel in the data and traces

`conversations.channel` is `web`, `whatsapp` or `voice` (`docs/database.md`). `handle_turn` stores
it on new conversations, includes it in the `chat turn` log line and tags the Langfuse trace
`channel:<name>`. The agent never sees it.

## Local tunnel (webhooks on your laptop)

A provider can only call a public https URL, so locally an ngrok tunnel exposes the `api` service.

1. Create a free account at https://dashboard.ngrok.com and copy your **authtoken**.
2. In the dashboard, **Domains**, claim your free static domain (`something.ngrok-free.app`).
3. In `.env`: `NGROK_AUTHTOKEN=...`, `NGROK_DOMAIN=something.ngrok-free.app` (no `https://`) and
   `PUBLIC_BASE_URL=https://something.ngrok-free.app`, plus the channel variables above.
4. `make tunnel` starts db, api (reload), web and ngrok. `make down` stops them all.
5. Open the inspector at http://localhost:4040: it lists every request the provider sent and lets
   you **Replay** one, which is the fast way to debug a webhook without sending real messages.

The `ngrok` service only gets `NGROK_AUTHTOKEN`; it does not read `.env`, so the tunnel never sees
the app's secrets. Anyone with the URL can reach `api` while it runs, which is why each channel
verifies its provider's signature.

## WhatsApp

Users write to a WhatsApp number through Twilio; the app answers through the same agent as the web
UI. Code: route `app/api/routes/channels/whatsapp.py`, `WhatsAppService`
(`app/services/whatsapp_service.py`), reply formatting (`app/services/whatsapp_format.py`) and the
Twilio REST wrapper `WhatsAppSender` (`app/clients/whatsapp_sender.py`).

### Setup with the Twilio sandbox

1. Create a Twilio account and open **Messaging > Try it out > Send a WhatsApp message**. It shows
   the sandbox number and a **join code** (`join <two-words>`).
2. From your phone, send that `join ...` message to the sandbox number. Each phone that wants to
   talk to the bot must do this once (the sandbox forgets it after 72 hours of silence).
3. In `.env`: `CHANNELS=web,whatsapp`, `CHANNEL_ID_SECRET`, `PUBLIC_BASE_URL` (the ngrok URL, see
   the tunnel above), `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` (Twilio console, Account info).
   Without all of them the app refuses to start.
4. `make tunnel`. In the sandbox settings, **When a message comes in**:
   `<PUBLIC_BASE_URL>/api/channels/whatsapp/webhook`, method **POST**. Save.
5. Write to the sandbox number. Watch the requests in the ngrok inspector
   (http://localhost:4040): **Replay** re-sends one without typing on your phone (a replayed
   `MessageSid` is dropped as a duplicate, so edit it first or send a new message).

`RATE_LIMIT_WHATSAPP` (default `10/minute`) limits messages per sender.

### What happens to a message

1. `POST /api/channels/whatsapp/webhook` (form-encoded by Twilio). In order: a body over 64 KB is
   `413`; the `X-Twilio-Signature` is checked with `RequestValidator(TWILIO_AUTH_TOKEN)` against
   `PUBLIC_BASE_URL + /api/channels/whatsapp/webhook`, never `request.url` (a proxy or the tunnel
   rewrites it), invalid is `403`; no `From` or `MessageSid` is `400`; a `MessageSid` already seen
   is answered `200` and ignored (Twilio retries).
2. The route answers `200` with an empty `<Response/>` immediately and schedules the work with
   `BackgroundTasks`.
3. `WhatsAppService` does the rest: per-sender limit (polite "wait a minute" message when over),
   media or empty text gets "I can only read text messages", otherwise `resolve` +
   `ChatService.handle_turn(..., channel="whatsapp")` under the per-visitor lock. If the turn
   fails the user gets a short apology instead of silence. Observability is flushed afterwards.
4. The reply is formatted for WhatsApp and sent with the REST API, from the number the user wrote
   to (the webhook's `To`), so there is no "from" setting.

Formatting runs after the output guardrails and never creates or changes a URL: `[text](url)`
becomes `text: url`, `**bold**` becomes `*bold*` (per line, WhatsApp does not bold across a line
break), headings become plain lines. Text over 1600 characters (Twilio's limit) is split into at
most 3 messages at paragraph, line or space boundaries, never inside a URL or a bold span; if text
remains after the third, it ends with "...".

### Why replies go through the REST API

Twilio waits about 15 seconds for the webhook response. A turn with tool calls or a fallback model
can take longer, and a TwiML reply that arrives late is lost. Answering the webhook immediately and
sending the reply with `messages.create` has no such deadline, and lets a long reply go out as
several messages. The cost is one extra Twilio API call per message.

### Limits

- **Deduplication and the per-visitor lock are per process** (in memory), like the lock in the
  conversation section. With several workers or instances a Twilio retry or two quick messages can
  be handled twice; the cost is a duplicated reply or conversation, not a lost one.
- **24-hour session window.** WhatsApp lets a business message a user freely only within 24 hours of
  the user's last message. Every reply here answers a user message, so it is inside the window.
  Starting a conversation or writing after the window needs a Meta-approved message template; that
  is not supported.
- **Serverless hosting.** On Vercel, work scheduled after the response is not guaranteed to run:
  the instance may freeze once the response is sent, and the reply would be lost. For WhatsApp,
  host the app where the process keeps running (the Docker image on a container host or a VM) until
  the work is moved to a queue or a durable function.
- Text only: images, audio and other media get the canned reply.
- Twilio's `From`, `To`, `WaId` and `ProfileName` are never logged or stored; logs carry
  `visitor_id`, `MessageSid` and Twilio error codes.

## Voice

Coming in a later change.
