# Commit 14 — FastAPI, SSE streaming, simple chat page

**Week 4 · depends on: 12**

## Context
The demo video needs a browser chat: streamed answers, visible citations, the refund order picker, and a visible handoff.
Keep it small: FastAPI + Server-Sent Events + one static HTML page with vanilla JS. No frontend build.

## Read first
- `AGENTS.md` §2 (UI choice), §5.4
- `graph/build.py`, `graph/state.py`, `graph/handoff.py`, the refund interrupt in `graph/nodes/refund/`
- LangGraph streaming docs for the installed version (`astream` with `stream_mode=["messages","updates"]` or equivalent)

## Task
1. `src/support_agent/api/app.py` — app factory `create_app(deps)`; builds the graph once at startup.
2. Endpoints:
   - `POST /api/chat` body `{conversation_id, customer_id, message}` → **SSE** stream of events:
     `meta` (intent, path — sent as soon as classify finishes), `token` (answer text deltas), `citations` (list), `interrupt` (order picker payload), `handoff` (reason + customer message), `done` (latency ms, token usage), `error`.
   - `POST /api/resume` body `{conversation_id, customer_id, value}` → same SSE stream, resumes an interrupt with `Command(resume=value)`.
   - `GET /api/health` → Milvus reachable, order DB present, models configured.
   - `GET /api/customers` → a few seeded demo customer ids with names (demo convenience only).
3. Only stream tokens from the **final answer** nodes (knowledge `answer`, tools path final message, refund `act`, complaint). Do not stream rewrite/classify/judge tokens to the user.
4. `src/support_agent/api/static/index.html` (+ small `app.js`, `style.css`):
   - Customer selector, message list, input box.
   - Streams text as it arrives; shows a small intent/path badge; renders `[1]` citations as hoverable chips showing the heading path; renders the order picker as buttons that call `/api/resume`; renders handoff as a distinct system bubble ("Transferred to a human agent — reason: …").
   - A "debug" toggle that shows the gate score and signals for the last turn (great for the demo).
5. `make serve` → uvicorn with reload off; prints the URL.
6. Conversation id = LangGraph thread id; the checkpointer persists across requests (SQLite saver when `api.persist=true`).

## Requirements
- Errors inside the graph become an `error` SSE event and a handoff message, never a hung stream.
- Request validation with Pydantic; `customer_id` must be one of the seeded customers (demo app, no auth — say so in README).
- CORS off by default.

## Tests
- `httpx.AsyncClient` + ASGI transport with fake deps: a knowledge question yields `meta → token… → citations → done` in order.
- Refund with no order id yields an `interrupt` event; `/api/resume` continues and ends with `done`.
- Graph exception → `error` event then stream closes.
- Health endpoint with fakes.

## Out of scope
Auth, deployment, styling beyond readable.

## Done when
- [ ] `make up && make serve` → chat at `http://localhost:8000/` handles: a policy question with citations, a refund with the picker, a gold-bars refusal
- [ ] `make check` green; PROGRESS row 14 updated
- [ ] Interview note `docs/notes/14-api-sse-ui.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(api): FastAPI SSE chat endpoint with interrupt resume and minimal chat page
```
