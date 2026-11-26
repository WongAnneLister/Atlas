# 30 — Governed long-term customer memory

**What**
I added a `customer_memories` table with a PostgreSQL migration, row-level security, and a scoped repository.
I built a write policy with kind, confidence, payment, third-party, and PII checks.
I wired frozen `L1_session` loading at turn one, `L4_turn` mid-chat lookup, and `/api/me/memories` controls.
I also built a thirty-scenario multi-session evaluation and documented the design in `docs/MEMORY.md`.

**Why**
Returning customers should not repeat owned products, open issues, or preferences across sessions.
Without strict rules, long-term memory leaks data between customers, stores junk, and breaks prefix caching.
Freezing `L1_session` at turn one keeps the cached prompt prefix stable across every turn.
Keeping memory as hints only stops old memories from bypassing the evidence gate.

**Number**
Across thirty live two-session scenarios, cross-session fact use rose from 0/10 to 10/10.
Stale-memory errors stayed at 0/8, cross-customer canary leaks were 0/6, and deletion held 6/6.
Storage averaged 100.7 bytes and 1.43 rows per customer, with 43 memories exported for review.
Source: eval/reports/archive/memory_long-3f046b8.md

**Trade-off**
I stored memories in PostgreSQL with per-customer scoring instead of a separate Milvus partition.
That limits recall to fifty active rows per customer, which is plenty for support profiles.
In return, deletion, expiry, and row-level security happen atomically in one transactional store.
Human review of the forty-three stored memories for junk rate is still pending.

**Likely follow-up question**
Q: How do you stop a mid-conversation memory lookup from breaking the prompt cache?
A: I load the top memories once on turn one and freeze `L1_session`.
Later turns never edit `L1_session`, even when new memories are found or written.
Extra mid-turn hints go into `L4_turn` for that single turn only.
Memories written during this chat take effect in the next session.
