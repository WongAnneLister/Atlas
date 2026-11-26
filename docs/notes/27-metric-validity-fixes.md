# 27 — Three metrics that measured the wrong thing

**What**
I fixed three evaluation metrics. Fact retention now scores only recall turns the chat reached. The cache metric now tracks only the layers meant to stay fixed. Memory use now needs the fact in the reply itself.

**Why**
All three gave confident numbers that meant nothing. Retention counted unasked questions as forgotten facts. The cache metric read 100% for every strategy. Memory use counted a memory as used once it was loaded.

**Number**
No number yet. I will measure it in the rescore commit that follows.

**Trade-off**
Some old report numbers are now stale. The cache and memory reports need live reruns, which cost model calls. Retention is still hard to measure, because the simulated user often stops early.

**Likely follow-up question**
Q: How did these bugs get through?
A: Each metric had unit tests, but on hand-made chats that fit the metric. Nobody checked the real transcripts behind a surprising number. Now I re-score saved transcripts before I trust a change.
