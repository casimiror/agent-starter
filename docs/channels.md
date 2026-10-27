# Channels

A **channel** is a way to reach the same agent besides the web UI: WhatsApp, voice. The agent,
its prompt, tools and guardrails are identical on every channel; a channel only brings messages
in, takes the reply out and says which conversation they belong to. The code of each channel lives
in this template and is tested in CI, but every channel is **off by default** and enabled by
configuration.

Status: the shared foundation, the WhatsApp channel and the voice channel (relay, gather and
realtime modes) are in place.

In a project created from the template, `/new-channel` does the setup below for you: it asks which
channels and which voice mode, writes the settings, fills the Channels section of `plan.md` and
guides the Twilio and ngrok test. `/kickoff` runs it, and `/deploy-setup` checks the channels
against the production host.

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
| `send_lock(visitor_id)` | Keeps one sender's replies in order; taken before `lock` is released |

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

Sending a reply is slow and can hang, so it is not done inside that lock. WhatsApp locks hand over
hand: inside `lock` it takes `send_lock(visitor_id)`, leaves `lock`, then sends. The sender's next
message can run its LLM turn while the previous reply is still going out, and replies still leave
in order. Each Twilio call has `TWILIO_SEND_TIMEOUT_SECONDS` (default 5), and the remaining parts
of a reply are dropped after the first failed one.

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
   fails the user gets a short apology instead of silence. If formatting the reply fails, the raw
   reply (cut to one message) is sent, never the apology. Observability is flushed afterwards.
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

People phone a Twilio number and talk to the same agent. Twilio's "A call comes in" webhook always
lands on `POST /api/channels/voice/incoming`; `VOICE_MODE` decides how the rest of the call works.

| `VOICE_MODE` | Who listens and speaks | The app talks to Twilio over | Needs | Limits |
| --- | --- | --- | --- | --- |
| `relay` (default, recommended) | Twilio ConversationRelay: speech-to-text and text-to-speech, with interruption | a WebSocket (JSON text) | a host that keeps WebSockets open; Voice AI addendum accepted in the console | not on Vercel functions |
| `gather` | Twilio `<Gather input="speech">` and `<Say>` | one HTTP webhook per turn | nothing but HTTP, so it works on serverless | the whole turn must fit in Twilio's ~15 s webhook timeout; plainer voice, less natural pauses |
| `realtime` | one speech-to-speech model (OpenAI Realtime) that hears and speaks, over Twilio Media Streams | a WebSocket (audio) | a host that keeps WebSockets open; `OPENAI_API_KEY` | not on Vercel functions; the model must handle audio natively; guardrails act on transcripts, weaker than in text (see [Realtime](#realtime)) |

Because Twilio does the speech in `relay` and `gather`, the agent only sees text: Claude and any
other text-only LLM work unchanged. `realtime` replaces the agent graph with an audio model, which
is why it needs its own section below. An unknown `VOICE_MODE` stops the app at startup. The
routes of the modes that are not selected answer 404.

Code: routes `app/api/routes/channels/voice.py` (`/incoming`), `voice_relay.py`, `voice_gather.py`,
`voice_realtime.py`; `VoiceService` (`app/services/voice_service.py`), `RelaySession`
(`voice_relay.py`), `RealtimeSession` and `RealtimeVoiceService` (`voice_realtime.py`,
`realtime_voice_service.py`), TwiML builders (`voice_twiml.py`) and the speech formatter
(`voice_format.py`).

### Setup

1. In the Twilio console buy (or use) a phone number with **Voice**. A trial account can only call
   verified numbers: verify yours in the console first.
2. Number settings > **A call comes in**: Webhook, `<PUBLIC_BASE_URL>/api/channels/voice/incoming`,
   method **HTTP POST**.
3. `relay` only: in the console's Voice settings accept the "Predictive and Generative AI/ML
   Features Addendum". ConversationRelay requires it.
4. `.env`: `CHANNELS=web,voice`, `CHANNEL_ID_SECRET`, `PUBLIC_BASE_URL`, `TWILIO_AUTH_TOKEN` (voice
   needs no account SID), and the voice variables below. Without the first four the app refuses to
   start.
5. Locally `make tunnel` (see above). ngrok carries `wss://` too, so the relay WebSocket works
   through the same domain. Then call the number and watch the requests in
   http://localhost:4040.

| Variable | Default | |
| --- | --- | --- |
| `VOICE_MODE` | `relay` | `relay`, `gather` or `realtime` |
| `VOICE_LANGUAGE` | `en-US` | speech recognition and voice language (BCP 47) |
| `VOICE_GREETING` | "Hello, thanks for calling. How can I help you today?" | first thing the caller hears |
| `VOICE_LINK_PHRASE` | "I can't read links aloud; you'll find it on our website." | said instead of any URL |
| `RATE_LIMIT_VOICE` | `5/minute` | calls per caller (anonymous visitor id) |
| `VOICE_MAX_CALL_SECONDS` | `600` | longest call |
| `VOICE_TTS_PROVIDER` | `ElevenLabs` | relay only: `Google`, `Amazon` or `ElevenLabs` |
| `VOICE_VOICE` | empty | relay only: the provider's voice name; empty is its default |
| `VOICE_TRANSCRIPTION_PROVIDER` | `Deepgram` | relay only: `Google` or `Deepgram` |

The `realtime` variables are in [Realtime](#realtime).

Pick a TTS voice that exists for the provider and language: Twilio ends the session on an invalid
provider/voice combination.

### What happens when a call comes in

`POST /api/channels/voice/incoming` (form-encoded by Twilio), in order: body over 64 KB is `413`;
`X-Twilio-Signature` checked against `PUBLIC_BASE_URL + path`, invalid is `403`; no `CallSid` is
`400`; `hit_sender(RATE_LIMIT_VOICE, "voice", visitor_id)`, over the limit the caller hears a short
message and `<Hangup/>`; otherwise a **new** conversation is created and the mode's TwiML answers.

**One conversation per call.** WhatsApp reuses a sender's conversation for 24 hours because a chat
has no end; a call does, and the next call should not inherit the last one's context (or its
history, which is sent to the model). So every call opens a conversation (`channel = 'voice'`) with
`ChannelConversations.start`. A caller with a hidden number (`From` empty or `anonymous`) is keyed
by the call's own SID so such callers do not share one visitor and one limit.

#### `relay`

`/incoming` answers `<Connect action=".../relay/action"><ConversationRelay url="wss://<host>/api/
channels/voice/relay/ws" welcomeGreeting language ttsProvider transcriptionProvider
interruptible="any">` with two `<Parameter>`s, `visitor_id` and `conversation_id`. Twilio then
opens the WebSocket:

1. **Handshake.** Twilio signs the `wss://` URL (no body) in `X-Twilio-Signature`. The route
   verifies it with `RequestValidator` against the URL built from `PUBLIC_BASE_URL`, accepting the
   URL with or without a trailing `/` (the docs do not say which form is signed), and closes with
   code 1008 (policy violation) before accepting otherwise.
2. `setup`: the two parameters bind the session to the conversation; it must exist and be a voice
   conversation, else the session ends. `from`, `callerName` and the other caller fields are ignored.
3. `prompt`: acted on only when `last` is true. The turn runs in a threadpool
   (`ChatService.handle_turn(..., channel="voice")`), the reply goes through `format_for_speech`
   and is sent as `{"type":"text","token":<reply>,"last":true}`. A failed turn sends a spoken
   apology. One turn at a time per call (a lock), so a caller who speaks twice gets two answers in
   order, never two concurrent turns. Observability is flushed after each turn.
4. `interrupt`, `dtmf`, `error`: logged (never the digit or the words), nothing sent back.
5. After `VOICE_MAX_CALL_SECONDS` the app sends `{"type":"end"}`; Twilio then closes the socket and
   calls the `action` URL, which answers `<Hangup/>` (`POST /api/channels/voice/relay/action`,
   signed; it logs `SessionStatus`, `SessionDuration` and `ErrorCode`).

**Interruptions do not trim history.** When the caller talks over the reply Twilio sends
`utteranceUntilInterrupt`, the part that was actually spoken. The stored assistant message keeps the
**whole** reply, so the history the model sees can hold words the caller never heard. Trimming it
would mean rewriting a stored message after the fact; it is not done.

#### `gather`

`/incoming` answers `<Gather input="speech" action=".../gather?c=<conversation_id>" method="POST"
speechTimeout="auto" language=...><Say>greeting</Say></Gather>` followed by a `<Redirect>` to the
same URL for when nothing is said. `POST /api/channels/voice/gather` (signed; the signature covers
the **full URL including `?c=`**, so the route validates the exact URL it emitted) reads
`SpeechResult`, runs the turn inside the request and answers `<Gather><Say>reply</Say></Gather>`
again, so the caller can talk over the reply (barge-in). The conversation id travels in the query
string (a UUID, not personal data) and must be an existing voice conversation, otherwise the call
ends politely and nothing is opened. Silence is re-prompted once (`&r=1`), the second silence hangs
up. The call also ends once it is older than `VOICE_MAX_CALL_SECONDS` (checked per turn, with the
conversation's creation time).

### Speech formatting

`format_for_speech` runs after the output guardrails and only ever removes: Markdown markers go,
links keep their text, headings and list items become sentences, and **every URL is removed** and
replaced, once at the end of the reply, by `VOICE_LINK_PHRASE`. It cannot invent a URL. In `gather`
a reply is also cut to 3500 characters at a sentence boundary (`<Say>` rejects more than 4096).
`realtime` does not use it: the model speaks directly, so no text passes through to format.

### Realtime

`VOICE_MODE=realtime` skips the cascade (speech to text, the agent graph, text to speech) and gives
the call's audio to a speech-to-speech model, OpenAI Realtime. The model listens and speaks
directly, which gives the lowest latency and natural interruptions, in exchange for the control the
graph gives the text channels (below).

```
 caller's phone            Twilio                          this app                         OpenAI
 ──────────────        ─────────────        ──────────────────────────────────────    ───────────────
 speaks  ───────────▶  Media Streams ─────▶ /api/channels/voice/stream (WebSocket)
                       (mu-law 8 kHz,        RealtimeSession ── input_audio_buffer ──▶  Realtime API
                        base64 JSON)           │                    .append (as is)      (gpt-realtime-2.1)
 hears  ◀───────────   media + mark   ◀─────  │  ◀── response.output_audio.delta ───
                       clear (barge-in)        │
                                               ├─ tools (the agent's) ◀─ function calls ─▶ run in a thread
                                               ├─ guardrails on transcripts: cancel + canned reply
                                               └─ messages table + one Langfuse trace per turn
```

Audio goes through unchanged: Twilio's mu-law (`audio/pcmu`) is configured as both the input and
the output format of the model, so nothing is transcoded.

#### Setup

1. As for the other modes: a Twilio number with **Voice**, **A call comes in** pointing at
   `<PUBLIC_BASE_URL>/api/channels/voice/incoming` (HTTP POST), `CHANNELS=web,voice`,
   `CHANNEL_ID_SECRET`, `PUBLIC_BASE_URL`, `TWILIO_AUTH_TOKEN`. The ConversationRelay addendum is
   not needed.
2. An OpenAI API key with access to the Realtime models in `OPENAI_API_KEY`. It is the key the
   `openai:` entries of `LLM_FALLBACKS` already use, so there is one place to set and rotate it.
   The app refuses to start in this mode without it.
3. `VOICE_MODE=realtime` and, optionally, the variables below.
4. Locally `make tunnel`; ngrok carries `wss://` too. Call the number and watch
   http://localhost:4040.

| Variable | Default | |
| --- | --- | --- |
| `VOICE_REALTIME_PROVIDER` | `openai` | only `openai` exists. Gemini Live would be another connector behind `RealtimeConnector` (`app/clients/realtime.py`); it is not built |
| `VOICE_REALTIME_MODEL` | `gpt-realtime-2.1` | `gpt-realtime-2.1-mini` is the cheaper option |
| `VOICE_REALTIME_VOICE` | `marin` | the model's voice; it can't change once the model has spoken in a call |
| `VOICE_REALTIME_TRANSCRIPTION_MODEL` | `gpt-4o-mini-transcribe` | transcribes the caller; the transcript feeds the guardrails and the stored history |

`VOICE_GREETING` is the first thing the caller hears (the model is told to say it word for word);
`VOICE_LANGUAGE`, `VOICE_TTS_PROVIDER`, `VOICE_VOICE` and `VOICE_TRANSCRIPTION_PROVIDER` are for
the other modes and ignored here.

#### What happens in a call

`/incoming` answers `<Connect><Stream url="wss://<host>/api/channels/voice/stream">` with one
`<Parameter name="conversation_id">` (the URL cannot carry a query string). Twilio then opens the
WebSocket.

1. **Handshake.** The `wss://` URL is signed like the relay's: verified against `PUBLIC_BASE_URL`
   with or without a trailing `/`, closed with 1008 before accepting otherwise.
2. **`start`** binds the session to the conversation (it must exist and be a voice conversation,
   else the call ends), opens `wss://api.openai.com/v1/realtime?model=...` with the key as a bearer
   token and sends `session.update`: `audio/pcmu` both ways, server-side voice detection
   (`server_vad`), input transcription, the voice, **the same prompt file as the text agent as
   `instructions`** (nothing is added per channel) and **the same tools** (`name`, `description`
   and the arguments' JSON schema of every tool in `build_assistant_tools`), `tool_choice: auto`.
   Caller audio is dropped until the model confirms the session (`session.updated`), then the
   greeting is said.
3. **Audio.** `media` from Twilio goes to `input_audio_buffer.append` untouched. The model's
   `response.output_audio.delta` goes back as `media`, each followed by a `mark`. Twilio echoes a
   mark when that chunk has *played*, which is how the app knows how much of a reply the caller
   heard (the model produces audio faster than it plays).
4. **Barge-in.** On `input_audio_buffer.speech_started`, if audio is still queued: Twilio `clear`
   (drops it) and `conversation.item.truncate` with `audio_end_ms` = the audio actually played, so
   the model's own memory of what it said matches what the caller heard. The reply's cancellation
   arrives as `response.cancelled` or as `response.done` with status `cancelled`; either closes it.
5. **Tools.** On `response.function_call_arguments.done` (or a `function_call` item in
   `response.done`, deduplicated by `call_id`) the tool runs in a threadpool with
   `config={"configurable": {"conversation_id": ...}}`, the per-turn context the text agent gives
   its tools. The result goes back as `conversation.item.create` (`function_call_output`) and then
   `response.create` once the response that made the call has finished. An unknown tool, unreadable
   arguments or a failing tool give the model an `UNKNOWN_TOOL:`, `BAD_ARGUMENTS:` or `TOOL_ERROR:`
   string; they never end the call. Arguments are never logged.
6. **Guardrails** (below).
7. **History.** When the caller has heard the reply, or it was cut, the turn is written to
   `messages` (the caller's transcript, then the assistant's transcript) and traced: one Langfuse
   trace per turn through `trace_turn`, tagged `channel:voice`, with `tools_called` and
   `blocked_by` as metadata and the tool results as `context`, then flushed. If the caller
   interrupted, the stored reply is the part that was played, **estimated** from the share of the
   audio that played (the transcript has no per-word timing), cut at a word boundary. The greeting
   is stored as an assistant message.
8. **End.** After `VOICE_MAX_CALL_SECONDS` both sockets are closed. Twilio's `stop` or a
   disconnect closes the model's socket; the model's socket closing, a connection failure or a
   fatal `error` event ends the call. Errors are logged by `type` and `code` only (`message` can
   quote the caller). Whatever was playing is stored as heard so far.

#### Guardrails on a speech-to-speech model

The same classes and canned texts as the text channels (`assistant_guardrails` in
`app/agents/assistant_agent.py`), applied to transcripts:

- **Input** guardrails run on each caller transcript (`conversation.item.input_audio_transcription.
  completed`). On a block the in-flight reply is cancelled (`response.cancel`), Twilio's queue is
  cleared, the reply is truncated, and the model is told, for that one response, to say exactly the
  guardrail's canned reply (`response.create` with `instructions`, tools off). The blocked turn is
  stored with the canned reply.
- **Output** guardrails run on the reply's transcript as it streams
  (`response.output_audio_transcript.delta`, only up to the last complete word so a half-written
  URL is not judged), and once more on the final transcript. On a block: cancel, clear, truncate,
  canned reply, as above.

**These are weaker than in text channels, and that is inherent.** In text the output is checked
before the user sees any of it; here the audio is already on its way. Transcription is also
asynchronous: the caller's transcript often arrives after the model started answering, and the
reply's transcript trails its audio. So **a few words can be heard before a block takes effect**,
and the checks only see what the transcript contains (a price said as "five hundred dollars" has
no `$`). The prompt and the tools' design remain the real boundary; treat these as a second line.
`format_for_speech` (which removes every URL from a reply) does not apply either: a link the model
says aloud is caught only if its transcript contains a URL outside `ALLOWED_LINKS`.

#### Costs

OpenAI bills audio tokens. For `gpt-realtime-2.1`, about $32 per million audio input tokens and $64
per million output tokens, roughly **$0.02 per minute of caller audio and $0.08 per minute of
assistant audio**; `gpt-realtime-2.1-mini` is about a third of that ($10 / $20 per million). The
input transcription model is billed separately (`gpt-4o-mini-transcribe`, about $0.003 per
minute). A 5-minute call with half of it spoken by each side is therefore around $0.25 with the full
model. Prices change: check OpenAI's pricing page. Twilio's per-minute voice and Media Streams
charges apply on top, as in the other modes. `VOICE_MAX_CALL_SECONDS` and `RATE_LIMIT_VOICE` bound
the spend per call and per caller.

#### Limits

- **Needs a WebSocket-capable, long-running host** (a container, a VM): two WebSockets are open for
  the whole call. Not Vercel functions.
- **A call lasts at most 60 minutes** on OpenAI's side (a Realtime session limit);
  `VOICE_MAX_CALL_SECONDS` (default 10 minutes) is the lower bound you set.
- **The model must handle audio natively.** Claude and other text-only models cannot be used here;
  `LLM_MODEL` and `LLM_PROVIDER` do not apply to this mode (they still serve the web and WhatsApp).
  To keep a text model on the phone, use `relay`.
- **State is per process**: the per-call state lives in the process that holds the WebSocket (it
  cannot move), and the caller limit counters, as in the other modes, are per process with
  `memory://`.
- **History is approximate**: a caller transcript that arrives after its reply has finished is
  stored with the next turn, and the "heard" part of an interrupted reply is an estimate.
- The caller's number is not sent to OpenAI (no `OpenAI-Safety-Identifier` header is set, and the
  stream carries no number) and is not stored or logged; logs hold `visitor_id`, `conversation_id`,
  `call_sid` and event types, never words.
- **Not verified against the live services yet**: the exact `session.update` shape, the
  `error` event's `type`/`code` values and the events used here
  (`response.output_audio_transcript.delta/done`, `response.function_call_arguments.done`,
  `response.cancelled`, `session.updated`, `tool_choice` on a per-response `response.create`) are
  written from OpenAI's reference as summarised, with a fallback or tolerance where the shape was
  uncertain. A real test call is the first thing to do with an API key.

### Limits

- `relay` needs a process that keeps a WebSocket open for the whole call (a container, a VM): not
  Vercel functions. `gather` needs only HTTP.
- `gather` is bound by Twilio's ~15 s webhook timeout: a turn with several tool calls or a fallback
  model can exceed it, and then the caller hears Twilio's error. There is no way around it in this
  mode; use `relay`.
- Interruptions do not trim the stored reply (above).
- The per-call lock, the per-visitor limit counters (with `memory://`) and the conversation checks
  are per process, like WhatsApp's. A call handled by several instances still works (each turn
  reads the conversation from the database); the cost is a looser limit.
- If a `relay` socket drops, Twilio does not reconnect: the call ends. A turn answered after the
  caller hung up is simply lost.
- The caller's number (`From`, `setup.from`, `callerName`) is only fed to
  `ChannelConversations.visitor_id`. It is never stored, logged, sent to Langfuse or put in TwiML;
  logs carry `visitor_id`, `CallSid`, `conversation_id` and Twilio error codes.
- Not verified against the live Twilio service yet: the exact URL form Twilio signs on the
  WebSocket handshake (both forms are accepted), and ConversationRelay's behaviour with each
  TTS/transcription provider and language.
