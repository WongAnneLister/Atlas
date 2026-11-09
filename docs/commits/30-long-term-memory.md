# Commit 30 — Long-term customer memory with a write policy, TTL, deletion and leak tests

**Phase 2 · Memory · depends on: 18, 21, 29, 35**

## Context
Returning customers should not repeat themselves ("I already reported this last week", preferred contact language, a known
defective device). But long-term memory is where agents leak data, store junk, and keep stale facts forever.
So memory is **governed**: a write policy decides what may be stored, every memory has provenance and an expiry, customers can
see and delete it, retrieval is strictly scoped to the customer, and evals check usefulness **and** safety.

## Read first
- `docs/THREAT_MODEL.md`, `memory/short_term/`, `context/builder.py`, `guardrails/pii.py`

## Task
1. **Schema** (Postgres migration): `customer_memories(id, customer_id, kind, content, structured jsonb, source_conversation_id, source_turn, created_at, last_used_at, expires_at, confidence, superseded_by, deleted_at)`.
   Kinds: `open_issue`, `preference`, `product_owned`, `past_resolution`. Optional embedding column for semantic recall (pgvector **or** a Milvus partition keyed by customer — choose and justify in `docs/MEMORY.md`).
2. **Write policy** — `src/support_agent/memory/long_term/policy.py`, at conversation end (or handoff):
   candidate memories extracted from pinned facts + summary by the `fast` model with structured output, then **code rules** decide:
   allowed kinds only; no payment data, no third-party personal data, no free-text over N chars; PII redaction; confidence ≥ threshold; dedupe against existing memories (update `last_used_at` / supersede instead of duplicating). TTL per kind in config.
3. **Read path** — at conversation start only: load the customer's non-expired memories (top-k by recency + relevance to the first message), render them deterministically into the `customer_profile` section (`L1_session`) with a small budget, each item marked with its date ("On 2026-10-02 you reported …"). `L1` is then **frozen for the conversation** so the cached prefix survives (see `docs/CONTEXT.md`). If a later turn needs a memory that was not loaded, fetch it by relevance and put it in `L4_turn` for that turn only. Memories written during this conversation take effect in the next one. Memories are **hints, never evidence**: they cannot satisfy the evidence gate and cannot change refund eligibility.
4. **Customer controls** — API: `GET /api/me/memories`, `DELETE /api/me/memories/{id}`, `DELETE /api/me/memories` (all). Chat page gets a small "What we remember" panel.
5. **Isolation** — every query filters by `customer_id` at the repository layer (no optional argument). Add a Postgres row-level-security policy or an equivalent repository guard, and a test that tries to bypass it.
6. **Eval** — `make eval-memory-long`:
   - Multi-session scenarios (extend the simulator: session 1 plants facts, session 2 days later needs them). ≥ 30 scenarios.
   - Metrics: cross-session fact use, redundant questions in session 2, **stale-memory errors** (fact changed between sessions — agent must prefer the new statement), **junk rate** (stored memories a human marks useless, via review CSV sample), **cross-customer leak rate** (canaries planted in other customers' memories — must be 0), deletion honoured (deleted memory never appears).
   - Compare memory off vs on with CIs; report storage per customer and added latency.

## Requirements
- Memory off by config → identical behaviour to commit 29.
- Nothing from long-term memory is ever cited as a source in answers.

## Tests
- Write policy accepts/rejects fixture candidates per rule; PII redacted; TTL set per kind.
- Supersede instead of duplicate.
- Repository guard: query without customer scope is impossible / raises.
- Deleted memories never returned; expired memories ignored.
- Gate ignores memory content (fake: strong memory, weak retrieval → still handoff).
- `L1` bytes identical on every turn of a conversation, even when a mid-conversation memory lookup adds items to `L4`.

## Out of scope
Organisation-wide memory (learning from all customers) — that is the handoff/feedback loop (31–32).

## Done when
- [ ] `eval/reports/memory_long.md`: usefulness and safety metrics with CIs, leak rate 0 (or listed failures)
- [ ] `docs/MEMORY.md` covers write policy, TTLs, isolation, controls
- [ ] `make check` green; PROGRESS row 30 updated
- [ ] Interview note `docs/notes/30-long-term-memory.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(memory): governed long-term customer memory with write policy, TTL, user controls and leak evals
```
