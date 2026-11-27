# 27 — Test-split reruns with the fixed simulator

**What**
I reran three reports on the test split with the fixed simulator. They cover the simulator baseline, the context builder and the short-term memory ablation. The old numbers came from a simulator that ended chats too early.

**Why**
The old reports could not test recall. Most chats ended before their fact checkpoints. So their fact retention numbers measured the simulator, not the agent.

**Number**
Simulator task success is 20.00% on 30 chats (`eval/reports/sim.md`). Only order status and self-correction chats succeeded. Fact checkpoints were probed 3 of 6 times, so retention is too small to read. In the memory report, all four arms had overlapping intervals.

Source: eval/reports/sim.md

**Trade-off**
Each report covers few chats, so the intervals are wide. The three runs used two commits. The second commit only adds a retry on the customer side.

**Likely follow-up question**
Q: Why is task success so low?
A: Most failures are handoffs on policy and refund chats. One cause I found is an answer prompt that skips its token budget. I have logged it and not fixed it yet.
