# Channels

A **channel** is a way to reach the same agent besides the web UI: WhatsApp, voice. The agent,
its prompt, tools and guardrails are identical on every channel; a channel only brings messages
in, takes the reply out and says which conversation they belong to. The code of each channel lives
in this template and is tested in CI, but every channel is **off by default** and enabled by
configuration.

Status: the shared foundation described here is in place. The WhatsApp and voice channels
themselves come in later changes.

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

Coming in the next change: Twilio webhook route, signature check, per-sender limit, reply
formatting.

## Voice

Coming in a later change.
