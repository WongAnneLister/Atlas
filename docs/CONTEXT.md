# Context engineering and prefix-cache design

Every LLM call in Atlas receives its prompt from one component: `ContextBuilder`
(`src/support_agent/context/builder.py`). No node concatenates chat history or pastes raw
tool outputs on its own.

## Five stability layers (`L0` to `L4`)

| Layer | Change cadence | Sections |
|---|---|---|
| `L0_global` | Never per deploy | Shared system preamble, safety rules, sorted tool names |
| `L1_session` | Once per conversation | Customer profile (populated in Commit 30) |
| `L2_compacted` | Every ~K turns | Frozen summary blocks produced by chunked compaction |
| `L3_history` | Append-only | Sanitized user and assistant turns (citations kept, raw chunks excluded) |
| `L4_turn` | Every turn | Node task instructions, current date, pinned facts, order context, compressed tool results, retrieved evidence, current user message |

**Why this exact order:** LLM providers and self-hosted engines (vLLM APC, SGLang) reuse the
KV cache of an identical prompt prefix. Any single changed byte invalidates every token after
it. Putting immutable instructions first (`L0`), session-scoped data next (`L1`), frozen
summary blocks in `L2`, append-only turns in `L3`, and all per-turn state at the end (`L4`)
maximizes prefix reuse across consecutive turns and across nodes (`rewrite`, `answer`,
`tools`, `decide`, `complaint`).

## Silent invalidators we eliminate

- No timestamps, request IDs, customer names, or feature flags in `L0_global`. Current date
  always lives in `L4_turn`.
- Deterministic serialization everywhere: `canonical_json` (`sort_keys=True`, compact
  separators) and alphabetically sorted tool names.
- Trimming happens **only inside `L4_turn`** (tool results via per-tool compressors, evidence
  lowest-rerank-first while never dropping below `good_count` chunks). If `never_trim`
  sections alone exceed budget, `ContextOverflow` triggers `HandoffReason.CONTEXT_OVERFLOW`.

## Chunked compaction and pinned facts

When `L3_history` exceeds `history_budget`, `compact_history` folds the oldest whole chunk of
`chunk_turns` atomic turns (never splitting a user/assistant pair or a tool call/result pair)
into a new immutable `SummaryBlock` appended to `L2_compacted`, compacting down to
`history_budget * low_watermark` for hysteresis. Existing summary blocks are never edited.
The summariser reuses the parent's `L0–L2` prefix verbatim, validates that every ID and number
appears in the source chunk, retries once on violation, and falls back to a deterministic
extractive summary.

Customer-visible facts (`order_id`, `model_number`, `date`, `amount`, self-corrections) are
tracked in `PinnedFacts` and rendered deterministically in `L4_turn`, so updating or
superseding a fact never invalidates the cached prefix.

## Provider cache adapter

`ContextBuilder` emits abstract breakpoints after `L0`, `L1`, `L2`, and `L3`.
`apply_cache_breakpoints` maps them per provider: Anthropic receives explicit `cache_control`
blocks (respecting `max_breakpoints` and `min_cacheable_tokens`, longest TTL first), while
OpenAI, DeepSeek, and non-caching providers receive plain messages.

## Trade-off and experiment results

Chunked compaction deliberately carries slightly more history tokens than aggressive per-turn
trimming, trading raw token count for prefix stability so most tokens are billed at the
provider's cache-read discount (0.1x on DeepSeek). In our four-arm A/B experiment on real
DeepSeek (`eval/reports/context_ab.md`), that trade-off held on billed input units: `chunked`
achieved the highest cache hit ratio (`79.9%`) and lowest effective input units per
conversation (`1300.1` vs `1941.5` for `sliding`, `1989.7` for `rolling`, and `6989.0` for
`chunked_nocache`), as well as the lowest P50 turn latency (`4.29 s` vs `9.61 s` / `9.96 s`).
On the dev-only `chunk_turns` sweep (4, 6, 10), `chunk_turns=6` kept the best balance of cache
hit ratio (`51.3%`) and task success (`33.33%`), so the default stays `6`. The optional vLLM
KV-level benchmark (`bench/kv/`) was skipped on this host because no NVIDIA GPU is present.

- Commit 28 ContextBuilder report: [eval/reports/context.md](../eval/reports/context.md)
- Commit 29 short-term memory ablation: [eval/reports/memory_short.md](../eval/reports/memory_short.md)
- Commit 35 4-arm prefix-cache A/B report: [eval/reports/context_ab.md](../eval/reports/context_ab.md)
