# 28 — Cache-aware ContextBuilder

**What**
I built one `ContextBuilder` that assembles every model prompt under a token budget.
It orders sections into five stability layers from immutable `L0` to per-turn `L4`.
Trimming happens only inside `L4`, and unfixable budget overflow hands off to a human.
I refactored every graph and grounding node to use it and added cache metrics.

**Why**
Before this commit, each node sliced chat history and pasted tool outputs on its own.
That broke prompt-prefix caching because one changed byte invalidates the rest of the prefix.
With one builder, all main nodes share an identical `L0` prefix and append-only history.
We also record exact token breakdowns and cache hit ratios for every model call.

**Number**
On 30 nightly test runs, DeepSeek prefix-cache hit ratios reached 85.1% on `classify`.
`tools` hit 64.7%, `decide` hit 67.6%, and `answer` hit 38.3% with 0/30 wrong accesses.
Task success was 26.67% versus 36.67% before, with overlapping intervals, and retention was 0.00%.
Source: eval/reports/context.md

**Trade-off**
Keeping `L0` to `L3` append-only means we do not trim old history every turn.
Until Commit 29 adds compaction, long chats rely on a temporary hard turn cap.
Moving node instructions into `L4` also slightly lowered task success on this small sample.
I kept the design honest and will fix fact retention next with pinned facts.

**Likely follow-up question**
Q: Why not just trim the oldest message on every turn to stay under budget?
A: Dropping the oldest turn shifts every byte after `L0` on every single turn.
That resets the provider's KV prefix cache to zero hits.
By keeping `L0` to `L3` append-only and trimming only `L4`, prefixes stay cached.
We shrink history only in chunks during compaction in Commit 29.
