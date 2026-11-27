# 29 — Cache-friendly short-term memory

**What**
I added pinned facts and chunked compaction to short-term conversation memory.
Pinned facts store order IDs, models, dates, and self-corrections in `L4`.
When history exceeds budget, chunked compaction folds whole chunks into frozen `L2` blocks.
Refund order identification now reads pinned order IDs before asking the user again.

**Why**
Long support chats overflow the history budget and lose early facts like order numbers.
Classic rolling summaries rewrite the prefix every turn and break KV prefix caching.
Frozen summary blocks keep `L0` to `L2` byte-identical between compaction points.
Putting pinned facts in `L4` lets us track corrections without changing the cached prefix.

**Number**
Across four ablation arms on 11 scenarios, task success stayed 27.27% with 0.00 redundant questions.
Cache hit ratio was 77.5% with both enabled versus 55.6% for the baseline.
Mean tokens per turn dropped from 3691.5 to 3402.8, with 0.00 compactions below budget.
Source: eval/reports/archive/memory_short-67616c1.md

**Trade-off**
Compaction did not fire in these short live runs because history stayed under budget.
If a summary invents a number, we retry once and fall back to extractive lines.
Extractive fallback is less fluent, but it never invents an order ID or amount.
I will stress-test chunked versus rolling compaction on longer chats in commit 35.

**Likely follow-up question**
Q: How do you handle a customer correcting their order number mid-chat?
A: The fact extractor detects correction phrases and marks the old order ID superseded.
Both stay in state, and `L4` renders the current ID with a note.
The refund node reads the latest active order ID instead of scanning old messages.
