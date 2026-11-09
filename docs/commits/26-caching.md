# Commit 26 — Caching that cannot serve stale or cross-customer answers

**Phase 2 · RAG · depends on: 22, 23, 25**

## Context
Many support questions repeat. Caching saves cost and latency, but a wrong cache is worse than none: it can serve an answer
from an old policy, or one customer's order details to another. Design caches so correctness is structural, then measure.

## Read first
- `docs/RETRIEVAL.md` (index lifecycle, `current_build_id()`), `docs/RELIABILITY.md`
- `infra/redis.py`, `retrieval/embed.py`, `retrieval/hybrid.py`, `graph/nodes/knowledge.py`

## Task
1. **Layer 1: embedding cache** — key `hash(embed_model, normalised_text)`, Redis, long TTL. Safe by construction.
2. **Layer 2: retrieval cache** — key `hash(rewritten_query, filters, build_id, retrieval_config_hash)` → reranked chunk ids + scores. Invalidated automatically by a new `build_id` (alias switch or incremental ingest bumps a per-build revision counter).
3. **Layer 3: answer cache (semantic)** — only for the **knowledge path**, only when:
   the intent is `policy_question` or `product_question`, no order context, no customer-specific data in the conversation's recent turns, gate passed, grounding passed.
   Key: exact match on normalised rewritten query + filters + build revision + prompt version + model. Optional near-duplicate match (embedding similarity ≥ high threshold) behind a flag — evaluate it, do not assume it is safe.
   The cached value stores the answer, citations and the gate/grounding verdicts.
4. **Never cache**: tools path, refund path, anything with an order id, guardrail-flagged turns.
5. Cache metrics: hit rate per layer, latency saved, cost saved (`/metrics` + e2e report).
6. **Correctness tests as eval**: `make eval-cache`:
   - Replay the eval set twice: second pass must give identical outcomes (exact cache) — compare with the eval platform.
   - Staleness: change a policy section (incremental ingest) → a cached question about it must miss and return the new answer.
   - Isolation: customer A asks a policy question with an order context → nothing cached; customer B never sees A's data (canary check).
   - Near-duplicate mode: measure wrong-hit rate on paraphrase pairs that should have **different** answers (e.g. W40 vs W40 Pro). If > 0, keep it off and say so.

## Requirements
- A cache miss path is identical to the no-cache path (tests compare outputs).
- Cache failures (Redis down) → bypass the cache, never fail the request.

## Tests
- Key builders include build revision, filters, prompt version, model (pure functions).
- Eligibility rules for the answer cache on fixtures.
- Redis down → bypass.

## Out of scope
CDN/HTTP caching.

## Done when
- [ ] `eval/reports/cache.md`: hit rates, latency/cost saved, staleness test, isolation test, near-duplicate wrong-hit rate
- [ ] `make check` green; PROGRESS row 26 updated
- [ ] Interview note `docs/notes/26-caching.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(rag): versioned embedding, retrieval and answer caches with staleness and isolation evals
```
