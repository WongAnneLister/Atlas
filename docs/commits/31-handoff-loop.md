# Commit 31 — Human handoff queue, agent console, and the improvement loop

**Phase 2 · Agent · depends on: 18, 19, 30**

## Context
In v1 a handoff is just a payload and a message. In production a human must pick it up, see why the AI stopped, reply inside
the same conversation, and resolve it. The resolved handoffs are also the best data we have: each one is a question the system
could not handle. This commit closes the loop: **handoff → human resolves with a label → new eval items and doc-gap reports**.

## Read first
- `graph/handoff.py`, `docs/RELIABILITY.md`, `docs/MEMORY.md`, `docs/EVAL_PLATFORM.md`

## Task
1. **Queue** (Postgres migration): `handoffs(id, conversation_id, customer_id, reason, priority, status[open|claimed|resolved], claimed_by, payload jsonb, created_at, claimed_at, resolved_at, resolution_label, resolution_note, idempotency_key)`.
   Priority rules in config (complaint and `guardrail_blocked` high; `low_evidence` normal).
2. **Conversation state** — after a handoff, the conversation enters `human_mode` in the graph (checkpointed): customer messages go to the queue item, not the AI, until resolved. On resolve, the human may hand back to AI.
   Implement with a graph interrupt or a mode flag checked at the graph entry — explain the choice in `docs/HANDOFF.md`.
3. **Agent console** — `api/static/console.html` + endpoints under `/api/agent/*` (demo agent token): list queue, claim, see payload (conversation, rewritten query, intent, gate signals, retrieval snapshot with scores, pinned facts, guardrail flags), reply (streamed to the customer's chat via SSE), resolve with a **label**:
   `kb_gap` (answer should exist in docs), `retrieval_miss` (docs had it, retrieval failed), `gate_too_strict`, `correct_handoff`, `policy_exception`, `abuse`.
4. **Loop outputs** — `make loop-report` (weekly job):
   - `kb_gap` → `eval/reports/doc_gaps.md` grouped by topic with example questions (input for writing new policy sections).
   - `retrieval_miss` and `gate_too_strict` → candidate eval items in `eval/sets/candidates_from_handoffs.jsonl` (with the human's answer as answer points), which go through the normal review workflow before entering a new eval set version.
   - Metrics: handoff rate by reason, time-to-claim, time-to-resolve, label distribution, and the share of handoffs that were `correct_handoff` (a direct measure of gate precision in "production").
5. Seed a realistic demo: run the scenario suite, let the console show real handoffs; resolve 20 by hand to demonstrate the loop (the human does the labelling; the agent must not).

## Requirements
- Claiming is atomic (no two agents claim one item). Idempotent handoff creation stays.
- The console shows exactly what the AI saw (from the trace), not a re-run.

## Tests
- Queue state machine (open → claimed → resolved; invalid transitions rejected); atomic claim under concurrency (integration).
- In `human_mode`, customer messages do not call any model (fake counts).
- Loop report on fixture resolved handoffs produces gap groups and candidate items.

## Out of scope
Real staffing features (SLAs per agent, routing by skill).

## Done when
- [ ] End-to-end demo: AI hands off → console claim → reply reaches the customer chat → resolve with label → appears in loop report
- [ ] `docs/HANDOFF.md` written
- [ ] `make check` green; PROGRESS row 31 updated
- [ ] Interview note `docs/notes/31-handoff-loop.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(handoff): human handoff queue, agent console, human mode and labelled resolutions feeding eval and doc-gap reports
```
