# Long-Term Customer Memory (`docs/MEMORY.md`)

Long-term customer memory lets returning customers avoid repeating durable facts across sessions (owned products, open issues, communication preferences, and past resolutions) while keeping privacy, prefix-cache stability, and evidence-gate safety intact.

## 1. Storage & Semantic Recall Choice

- **Schema**: `customer_memories` in PostgreSQL (Alembic migration `0004_customer_memories.py`) and SQLite for local offline tests (`src/support_agent/memory/long_term/tables.py`).
  - Columns: `id`, `customer_id`, `kind`, `content`, `structured` (JSON/JSONB), `embedding` (optional JSON float vector), `idempotency_key`, `source_conversation_id`, `source_turn`, `created_at`, `last_used_at`, `expires_at`, `confidence`, `superseded_by`, `deleted_at`.
- **Why Postgres + per-customer scoring instead of a Milvus partition**:
  1. **Single transactional trust boundary**: Soft deletion (`DELETE /api/me/memories`), TTL filtering, superseding, and Postgres Row-Level Security (`FORCE ROW LEVEL SECURITY`) execute atomically in one store. A separate vector index introduces eventual consistency and deletion lag.
  2. **Zero cross-customer index leakage**: Each customer is capped at `max_memories_per_customer` (default 50 active rows). Scanning <= 50 rows for one `customer_id` takes <1 ms in Postgres/SQLite, making lexical overlap + optional cosine similarity on the stored `embedding` column both faster and strictly isolated compared to managing per-customer Milvus partitions.

## 2. Governed Write Policy (`src/support_agent/memory/long_term/policy.py`)

Memories are proposed at conversation end or handoff by the `fast` model using structured output (`extract_memories.md`), then filtered by deterministic code rules before any write:

| Rule | Behaviour | Config key |
|---|---|---|
| Allowed kinds | Only `open_issue`, `preference`, `product_owned`, `past_resolution` | `memory.long_term.allowed_kinds` |
| Confidence floor | Reject candidates below threshold | `memory.long_term.min_confidence` (`0.7`) |
| Payment data | Reject card numbers (Luhn via `guardrails/pii.py`) and payment keywords (CVV, IBAN, bank account, etc.) | Code rule |
| Third-party personal data | Reject references to other people's personal details (spouse, friend, coworker, etc.) | Code rule |
| PII redaction | Run `redact_pii()` on `content` and string values in `structured` | `guardrails/pii.py` |
| Length bounds | Reject empty/short junk (<6 chars) or long free-text (>240 chars) | `min_content_chars`, `max_content_chars` |
| Dedupe & supersede | Exact/near-duplicate (Jaccard >= 0.80) refreshes `last_used_at` and `expires_at`; same kind + subject or Jaccard >= 0.45 inserts a new row and marks the old row `superseded_by` | `dedupe_similarity_threshold`, `supersede_similarity_threshold` |
| Idempotency | Unique `(customer_id, idempotency_key)` prevents retry duplicates | `uq_customer_memories_idempotency` |

### Default TTLs per Kind (`configs/default.yaml`)

| Kind | TTL (days) | Rationale |
|---|---:|---|
| `open_issue` | 30 | Active defects/cases expire if not resolved or refreshed |
| `past_resolution` | 90 | Recent refunds/replacements stay relevant for follow-ups |
| `preference` | 365 | Language/format preferences are durable |
| `product_owned` | 365 | Owned devices remain relevant across the warranty window |

## 3. Read Path, Prefix-Cache Freezing & Safety Boundary

- **Conversation start (`L1_session`)**: On turn 1 only (`not state.customer_profile_loaded`), `load_session_profile()` loads the customer's active, non-expired memories, ranks them by recency + relevance to the first message, and renders up to `session_top_k` (default 5) within `session_budget_tokens` (default 300) in canonical `(created_at, id)` order. Each line carries its date (`On YYYY-MM-DD (kind): ...`).
- **Frozen `L1_session`**: Once loaded on turn 1, `customer_profile` is persisted in graph state and never mutated during the conversation, keeping `L0_global + L1_session` byte-identical across all turns for provider prefix caching (see `docs/CONTEXT.md`).
- **Mid-turn recall (`L4_turn`)**: On later turns, `lookup_turn_memories()` checks non-loaded memories for relevance >= `mid_turn_min_relevance` (0.35) and injects up to `mid_turn_top_k` (2) into `L4_turn` for that turn only.
- **Next-session visibility**: Memories written during conversation N take effect in conversation N+1.
- **Hints, never evidence**: Memory content never enters `gate.evaluate()`, never appears in `[n]` citations, and cannot override `OrderService` facts or refund eligibility. When `memory.long_term.enabled` is `false` (default), behaviour is identical to Commit 29.

## 4. Isolation & Customer Controls

- **Repository guard**: Every method on `CustomerMemoryStore` requires a concrete, non-empty, non-wildcard `customer_id`; blank or wildcard values raise `CustomerScopeError`.
- **Database Row-Level Security (Postgres)**: Migration `0004_customer_memories.py` enables `FORCE ROW LEVEL SECURITY` on `customer_memories` with policy `customer_id = current_setting('app.customer_id', true)`, bound transaction-locally on every connection via `set_config('app.customer_id', :cid, true)`.
- **Customer API** (Bearer session token required via `SessionAuthMiddleware`):
  - `GET /api/me/memories` — list active non-expired memories for the signed-in customer.
  - `DELETE /api/me/memories/{id}` — soft-delete one memory owned by the signed-in customer (404 if absent or owned by another customer).
  - `DELETE /api/me/memories` — soft-delete all memories for the signed-in customer.
- **Chat UI**: The static chat page includes a collapsible **"What we remember"** panel with per-item Delete and "Forget all" controls.

## 5. Evaluation

Run `make eval-memory-long` (`eval/memory_long_eval.py`) to compare `memory_off` vs `memory_on` across 30 two-session scenarios (10 recall, 8 stale-update, 6 cross-customer canary leak, 6 deletion). Results are written to `eval/reports/memory_long.md` and stored memories are exported to `eval/reports/memory_long_review.csv` for human junk-rate review.
