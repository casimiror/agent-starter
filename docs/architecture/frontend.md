# Frontend architecture

React 19 + Vite + TypeScript in `frontend/`. A single chat feature; FastAPI serves the build.

## Structure: one folder per feature

```
frontend/src/
  main.tsx, App.tsx          # bootstrap and page shell
  styles.css                 # design tokens and component styles (see docs/design/frontend.md)
  features/chat/
    api/chatClient.ts        # the only place that knows the HTTP contract
    hooks/useChat.ts         # all chat state and side effects
    components/              # ChatWindow (container), MessageList, MessageContent, FeedbackButtons, MessageInput
    types.ts                 # mirrors backend app/schemas/chat.py
```

`features/eval/` is the `/eval` page (see `docs/evaluation.md`). `App.tsx` picks the page from
`window.location.pathname`; there is no router dependency.

A new capability gets its own `features/<name>/` with the same sub-folders. Features don't import
each other's internals; shared code goes to `src/shared/` when a second feature needs it.

## Layers

```
components (render)  ->  hook (state, effects)  ->  api client (HTTP)  ->  /api/*
```

Same idea as the backend layering: each layer only talks to the next one.

- **API client** (`api/`): wraps `fetch`, maps HTTP status to `ChatApiError` with a user-facing
  message (429 -> "sending messages too fast"). Hooks never see `fetch` or status codes.
- **Hook** (`hooks/`): owns state (`messages`, `pending`, `error`, `conversationId`, `visitorId`)
  and side effects (API calls, `localStorage`). Exposes plain values and callbacks.
- **Container component** (`ChatWindow`): calls the hook and passes data down. No markup logic of
  its own beyond layout.
- **Presentational components** (`MessageList`, `MessageInput`): props in, markup out. Only local UI
  state (the input's text). No API calls, no storage.

## Contracts with the backend

`types.ts` mirrors `backend/app/schemas/chat.py` by hand. A schema change means changing both
sides in the same commit.

## Rendering replies

Assistant replies are Markdown (`MessageContent`, `react-markdown` + `remark-gfm` for lists, tables
and bare-URL links). User text is rendered as typed. Raw HTML in Markdown is never rendered, and
links open in a new tab with `rel="noopener noreferrer"`; which URLs can appear is the backend
output guardrail's job.

## Feedback on replies

Assistant messages from the server carry their server id, `rateable: true` and `rating`. The local
greeting is not rateable. `useChat().rate(message, rating | null)` updates the thumb optimistically
and reverts it, with an error line, if `rateMessage` fails (`PUT` to set, `DELETE` to remove).
`FeedbackButtons` is presentational: clicking the active thumb sends `null`.

## Browser storage

`localStorage` keys, prefixed with `APP.storagePrefix` (`src/config.ts`): `<prefix>.conversationId`
(resume a conversation after reload) and `<prefix>.visitorId` (anonymous UUID, Langfuse user id).
Every access is wrapped in `try/catch`:
private mode must still work, just without persistence.

## React rules that bit us

- An effect may only return a cleanup function. Use a block body
  (`useEffect(() => { el.scrollIntoView(); }, [...])`): newer Chrome returns a Promise from
  `scrollIntoView`, and an expression body returned it, crashing React.
- `StrictMode` runs effects twice in dev; effects must be idempotent.

## Dev and build

- Dev: `make dev` runs Vite on :5173 and proxies `/api` to the `api` service
  (`API_PROXY_TARGET`, see `vite.config.ts`).
- Build: `tsc -b && vite build`. Docker copies `dist/` to `/app/static`; Vercel's
  `backend/vercel-build.sh` copies it to `backend/static`. Both are the default `FRONTEND_DIST`.
- No frontend tests yet.
