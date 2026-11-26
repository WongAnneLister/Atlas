# 35 — Prefix-cache context strategy A/B experiment

**What**
I added a strategy switch for sliding, rolling, chunked, and uncached context layouts.
I built a four-arm A/B harness with cost decomposition and a dev `chunk_turns` sweep.
I also added an optional vLLM KV-cache benchmark script and documented the design in `docs/CONTEXT.md`.

**Why**
Commits 28 and 29 claimed that append-only chunked compaction beats sliding windows and rolling summaries.
Without a controlled A/B test on the same scenarios, that claim is just a guess.
Comparing `chunked` against `chunked_nocache` also separates caching savings from layout changes.
The dev sweep lets us pick `chunk_turns` without tuning on test data.

**Number**
On six test scenarios, `chunked` hit 79.9% cache reads and cost 1300.1 units.
`sliding` cost 1941.5 units at 77.8% hits, and `rolling` cost 1989.7 at 68.9%.
Without caching, `chunked_nocache` cost 6989.0 units, while `rolling` had 16.67% task success.
Source: eval/reports/archive/context_ab-5449ce2.md

**Trade-off**
The test sample had six scenarios, so task success intervals are wide and noisy.
I reported `rolling` scoring higher on task success rather than hiding it.
No NVIDIA GPU was available here, so the self-hosted vLLM KV benchmark skipped cleanly.
Even so, the cost decomposition clearly shows prefix caching drives most of the savings.

**Likely follow-up question**
Q: Why did `rolling` have a lower cache hit ratio than `chunked`?
A: Rolling summaries rewrite the `L2` summary block whenever history compacts.
Changing `L2` invalidates every cached token after it in the prompt.
Chunked compaction appends a new frozen block and leaves older blocks untouched.
That kept cache hits at 79.9% versus 68.9% for rolling.
