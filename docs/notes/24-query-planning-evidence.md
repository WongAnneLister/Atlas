# 24b — Query planning evidence

**What**
I measured query planning and partial answers with real models. I compared planning off, planning on, and planning with partial answers. I used eval_v1 and a new set of two-part questions, on dev and test.

**Why**
Commit 24 only had fake-model tests. I needed to know if splitting a question helps customers. I also had to show that no new wrong answers slipped through.

**Number**
On half-answerable test questions, partial answers gave a correct cited answer 13 of 20 times. Without them it was 0 of 20. No unanswerable question got an answer in any run. On eval_v1 test, false rejects stayed at 13 of 120.
Source: eval/reports/query_planning.md

**Trade-off**
Split questions are slower: P95 latency rose from 14.3 to 21.4 seconds. Splitting alone did not fix misrouted questions. My cheap pre-check missed 11 of 50 test questions. I chose not to tune it on this set.

**Likely follow-up question**
Q: Why did the release gate fail first?
A: One recall metric only read the merged list of a split question. I fixed it to read each part, with a test first. Then the same saved run passed.
