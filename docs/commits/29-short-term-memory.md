# Commit 29 — Short-term memory: chunked compaction + pinned facts (cache-friendly)

**Phase 2 · Memory · depends on: 28**

## Context
With `ContextBuilder`, history (`L3_history`) is append-only, so it eventually overflows its budget. Commit 28 left a temporary
hard cap there. Long conversations then lose facts (order id from turn 2, "I already tried resetting it").

The classic fix — keep the last N turns, compress the middle, rewrite a running summary **every turn** — changes the prompt
prefix every turn and destroys prefix (KV) caching. Instead we use **chunked compaction**:

- History grows append-only.
- When `L3_history` exceeds its budget, the oldest **chunk** of K turns (not one turn) is folded into a new **frozen summary block**
  appended to `L2_compacted`. Existing summary blocks are never edited.
- When `L2_compacted` itself exceeds its budget, the oldest summary blocks are merged into one (a rare, second-level compaction).

So the prefix changes only at compaction points (every ~K turns), not every turn.

**Pinned facts** — order ids, product models, the customer's own problem statements (verbatim), decisions made, handoff status —
live in `L4_turn` (small, always present), so adding a fact never breaks the cached prefix.

## Read first
- `eval/reports/sim.md`, `eval/reports/context.md` (fact retention, redundant questions, cache hit ratio to keep or beat)
- `context/builder.py`, `context/sections.py`, `graph/state.py`

## Task
1. `src/support_agent/memory/short_term/facts.py` — `PinnedFacts` with typed entries `{kind, value, source_turn, verbatim?, superseded_by?}`.
   Extraction: regex first (order ids, model numbers, dates, amounts); `fast` model for problem statements and decisions (structured output). **Corrections**: "sorry, I meant 1043" supersedes 1042 (keep both, mark the old one superseded; render only current facts plus a one-line note of the correction).
   Rendered deterministically (sorted by kind, then turn) into `L4_turn`.
2. `src/support_agent/memory/short_term/compaction.py`:
   - Trigger: `L3_history` tokens > `history_budget` → take the oldest `chunk_turns` (config, e.g. 6) turns, never splitting a user/assistant pair or a tool call from its result.
   - Summarise **that chunk only** with the `fast` model; the summariser call reuses the parent's `L0–L2` prefix verbatim and appends the chunk + instructions at the end (so it reads from cache).
   - Validate: every id/number in the summary must appear in the chunk; otherwise retry once, then fall back to an extractive summary (key lines kept verbatim). Log the outcome.
   - Append the block to `L2_compacted` as `{block_id, turns: [a, b], text, created_at_turn}`; remove those turns from `L3_history`. Existing blocks are immutable.
   - Second-level: if `L2_compacted` > `summary_budget`, merge the oldest blocks into one (rare; count how often).
   - Hysteresis: compact down to `history_budget × low_watermark` (e.g. 0.6), so compaction does not fire again on the next turn.
3. Replace the temporary hard cap from commit 28 with compaction. Store layers in graph state so they persist with the checkpointer.
4. The rewrite node and tools/refund nodes read pinned facts (e.g. refund `identify_order` checks pinned order ids before asking).
5. Config: `chunk_turns`, `history_budget`, `summary_budget`, `low_watermark`, summariser model, `memory.short_term.enabled`, and `memory.short_term.strategy: chunked | rolling` (`rolling` = classic per-turn rewrite, kept **only** as a baseline for commit 35).
6. **Eval** — `make eval-sim` (full suite) + a long-conversation subset (25–30 turns). Compare commit-28 baseline vs + short-term memory. Metrics: fact retention, redundant questions, task success, tokens per turn, **cache hit ratio**, compaction events per conversation, summariser calls and cost, first-token latency. Paired CIs. Ablation: pinned facts only / compaction only / both.

## Requirements
- With `enabled=false`, behaviour equals commit 28 (compare → no significant change).
- Between compaction events, consecutive turns keep a byte-identical `L0–L2` prefix and an append-only `L3` (test it).
- Pinned facts and summaries never include data the customer could not see (internal order fields stay out).

## Tests (fakes only)
- Pinned facts: extraction, supersede ("1042" then "I meant 1043"), deterministic rendering.
- Compaction fires only above budget, compacts whole chunks, never splits a tool call/result pair, respects the low watermark.
- Existing summary blocks are never modified (hash before/after).
- Invalid summary (new number) → retry → extractive fallback.
- Summariser request starts with the parent's exact `L0–L2` bytes.
- Prefix stability across a 30-turn fake conversation: prefix changes only at compaction turns; count them.
- Pinned order id survives 30 turns; refund `identify_order` uses it without asking again.

## Out of scope
Cross-session memory (30). The chunked-vs-rolling-vs-sliding experiment and KV benchmark (35).

## Done when
- [ ] `eval/reports/memory_short.md`: comparison + ablation with CIs, including cache hit ratio and compaction frequency
- [ ] `make check` green; PROGRESS row 29 updated
- [ ] Interview note `docs/notes/29-short-term-memory.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(memory): cache-friendly short-term memory with chunked compaction into frozen summary blocks and pinned facts
```
