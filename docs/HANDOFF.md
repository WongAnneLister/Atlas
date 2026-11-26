# Human Handoff Queue, Console & Improvement Loop (`docs/HANDOFF.md`)

When Atlas cannot safely answer a customer question (low evidence, complaint, guardrail block, or policy exception), it hands off to a human agent, switches the conversation into `human_mode`, streams human replies back to the customer chat, and feeds labelled resolutions back into documentation gaps and eval candidates.

## 1. Queue Schema & Atomic Claim (`src/support_agent/handoff/`)

- **Migration**: `migrations/versions/0005_handoffs.py` creates `handoffs(id, conversation_id, customer_id, reason, priority, status, claimed_by, payload, created_at, claimed_at, resolved_at, resolution_label, resolution_note, idempotency_key)`.
- **Idempotency**: `enqueue()` deduplicates on `idempotency_key` (unique constraint), matching the per-turn action key generated in `graph/handoff.py`.
- **Priority rules** (`configs/default.yaml` → `handoff.priorities`): `complaint` and `guardrail_blocked` are `high`; `low_evidence`, `policy_requires_human`, and others are `normal`. Queue listings order `high` before `normal` before `low`, then oldest first.
- **State machine**: `open` → `claimed` → `resolved`. Invalid transitions (resolving before claiming, replying before claiming, claiming a claimed/resolved item, resolving by another agent) raise `HandoffStateError` (HTTP 409).
- **Atomic claim**: `claim()` executes a single conditional SQL update (`UPDATE handoffs SET status='claimed', claimed_by=:agent, claimed_at=:now WHERE id=:id AND status='open'`) inside a transaction and checks `rowcount == 1`. Under concurrent claims, exactly one agent wins.

## 2. Why a Checkpointed `human_mode` Flag Instead of `interrupt()`

We implemented human takeover with checkpointed `human_mode: bool` and `active_handoff_id: str | None` fields checked at `START` in `build_graph()`, rather than a LangGraph `interrupt()`:

1. **Multi-message customer follow-ups**: While waiting for a human agent, a customer can send additional context through normal `POST /api/chat` requests. An `interrupt()` only accepts a single `Command(resume=...)` payload, whereas `START -> human_mode -> END` forwards every follow-up message directly to the queue item with **zero LLM calls**.
2. **Out-of-band agent resolution**: The human agent resolves the ticket from `/console` (`POST /api/agent/handoffs/{id}/resolve`), not from the customer's chat input. On resolution with `hand_back_to_ai: true`, the API clears `human_mode` in the LangGraph checkpoint via `graph.update_state()` so the customer's next message resumes AI handling.

## 3. Agent Console & Live SSE Delivery

- **UI**: `/console` (`src/support_agent/api/static/console.html`) is a static page served by FastAPI.
- **Auth**: All `/api/agent/*` endpoints require `Authorization: Bearer <token>` matching `AGENT_TOKEN` (or `handoff.demo_agent_token`). There is no default. Without a private token the endpoints return `503`, and the old public value `atlas-demo-agent` is always refused.
- **Exact AI trace snapshot**: `GET /api/agent/handoffs/{id}` displays the frozen `HandoffPayload` captured at handoff time (conversation, rewritten query, intent, gate score and signals, retrieval snapshot with rerank scores, pinned facts, guardrail flags) — never re-run.
- **Live replies**: `POST /api/agent/handoffs/{id}/reply` persists the reply and publishes an `agent_reply` event on `HandoffEventBroker`; the customer's chat page subscribes to `GET /api/conversations/{conversation_id}/events` (Bearer customer token) to display replies and resolution notices in real time.

## 4. Improvement Loop (`make loop-report`)

Resolved handoffs require one of six labels: `kb_gap`, `retrieval_miss`, `gate_too_strict`, `correct_handoff`, `policy_exception`, `abuse`.

Running `make loop-report` (`eval/loop_report.py`) generates:
- `eval/reports/doc_gaps.md` — `kb_gap` resolutions grouped by topic/intent with example questions and notes.
- `eval/sets/candidates_from_handoffs.jsonl` — unreviewed (`reviewed: false`) candidate eval records from `retrieval_miss` and `gate_too_strict` resolutions using the human agent's reply as `answer_points`.
- `eval/reports/handoff_loop.md` — handoff share by reason, time-to-claim, time-to-resolve, label distribution, and `correct_handoff` share (gate precision proxy).

To seed open demo handoffs for manual human labelling in `/console`, run `make seed-handoff-demo`. Human labels must always be assigned by a human reviewer, never by the agent.
