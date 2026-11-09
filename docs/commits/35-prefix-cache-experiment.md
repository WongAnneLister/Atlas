# Commit 35 — Prefix-cache experiment: context strategies A/B, and a KV-level benchmark

**Phase 2 · Context management · depends on: 29 (run right after 29, before 30)** — numbered 35 only because it was added later

## Context
Commits 28–29 claim that a stability-ordered, append-only layout with chunked compaction beats the usual approaches on cost and
latency **without** hurting quality. This commit proves or disproves it with one controlled experiment, and adds an optional
self-hosted benchmark that shows the effect at the KV-cache level (prefill reuse), not just on the provider's bill.

## Read first
- `eval/reports/context.md`, `eval/reports/memory_short.md`
- `context/`, `memory/short_term/`, `docs/EVAL_PLATFORM.md`
- vLLM docs on Automatic Prefix Caching (APC) for the installed version (part B only)

## Task

### A. Context strategy A/B on the provider API (required)
1. Add a config switch `context.strategy` with four arms (all other settings identical):
   - `sliding` — keep the last N turns, drop the oldest every turn (the naive baseline; prefix changes every turn)
   - `rolling` — last N turns + a summary rewritten every turn
   - `chunked` — commit 29 design (append-only history, frozen summary blocks, compaction every ~K turns)
   - `chunked_nocache` — same as `chunked` but cache breakpoints disabled (isolates the effect of caching from the effect of layout)
   Match the **average** history token budget across arms as closely as possible and report the achieved averages.
2. `eval/context_ab.py` + `make eval-context-ab` — run the multi-turn scenario suite (commit 27) and the long-conversation subset under each arm. Per turn record: input tokens, cache-read tokens, cache-write tokens, cost (with the provider's cache read/write multipliers from config), first-token latency, `prefix_hash`.
3. Metrics per arm (paired across arms on the same scenarios, bootstrap CIs):
   - quality: task success, fact retention, redundant questions, false-accept on knowledge turns (must stay 0)
   - efficiency: cache hit ratio, prefix change rate (turns whose `L0–L2` hash changed / total turns), cost per conversation, first-token latency P50/P95, total input tokens
   - a **cost decomposition**: uncached input, cache writes, cache reads, output — to show *where* the savings come from (layout vs caching)
4. Sensitivity: sweep `chunk_turns` (e.g. 4, 6, 10) for `chunked`. Larger chunks → fewer prefix changes but longer contexts. Plot cost and hit ratio vs `chunk_turns`.
5. Report `eval/reports/context_ab.md` with tables, a cumulative-cost-by-turn chart per arm, and a written conclusion that includes any arm where `chunked` **lost**. Pick the default `chunk_turns` from **dev** scenarios only.

### B. KV-level benchmark on a self-hosted model (optional, behind `make bench-kv`)
6. `bench/kv/` — docker compose (or instructions) for vLLM with a small open model on a GPU. Skip cleanly and say so if no GPU is available.
7. Replay the **same rendered prompts** recorded in part A (saved as JSONL) against vLLM with APC on and off. Measure time-to-first-token, prefill throughput, and GPU KV-cache usage/hit stats (vLLM metrics endpoint). Compare `sliding` vs `chunked` prompt sequences.
8. Add results to `eval/reports/context_ab.md` → "KV-level view". Note clearly that the model differs from the production model; the point is the mechanism (prefix reuse), not absolute numbers.

### C. Docs
9. `docs/CONTEXT.md` (create): the layer model (L0–L4), why the order, the compaction design, the cache adapter, silent invalidators, and the experiment results with links. Include the trade-off in one paragraph: chunked compaction carries slightly more history tokens than aggressive per-turn trimming, but most of them are billed at cache-read price — report whether that held.

## Requirements
- Same scenarios, same models, same seeds across arms; the only difference is `context.strategy`.
- No tuning on test scenarios; report test.
- If the provider used has no prompt caching, part A still runs (hit ratio 0) and the report says the cost comparison is then about layout only.

## Tests
- Each strategy's renderer on a fixed fake conversation: `sliding` changes the prefix every turn, `rolling` changes `L2` every turn, `chunked` changes the prefix only at compaction turns (assert the hash sequence).
- Cost decomposition math on fixture usage records.
- Bench harness skips cleanly without GPU.

## Out of scope
Changing the provider or model to chase cache prices.

## Done when
- [ ] `eval/reports/context_ab.md` with 4-arm comparison (quality + efficiency, CIs), `chunk_turns` sensitivity, cost decomposition
- [ ] `docs/CONTEXT.md` written; KV-level section filled or marked "skipped: no GPU"
- [ ] `make check` green; PROGRESS row 35 updated with hit ratio and cost per conversation for each arm
- [ ] Interview note `docs/notes/35-prefix-cache-experiment.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): context strategy A/B for prefix caching (sliding, rolling, chunked) with cost decomposition and optional vLLM KV benchmark
```
