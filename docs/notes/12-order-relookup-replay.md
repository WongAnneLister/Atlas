# 12 — Measuring the order re-read fix by replay

**What**
I replayed the two chats where the order bug appeared. Each ran five times with the fix on and five times with it off. The customer messages were the recorded ones; the agent ran for real.

**Why**
The bug was rare, so new simulated chats did not hit it again. A replay sends the same messages, so it tests the exact failing turn.

**Number**
With the fix off, one chat hit a tool error in 3 of 5 replays. With the fix on, it never did, in 0 of 5. The other chat did not show the bug in either arm.
Source: eval/reports/order_relookup_replay.md

**Trade-off**
Five replays per arm give wide intervals, and they overlap. So the direction is clear, but it is not yet a firm result. More replays would cost more model calls.

**Likely follow-up question**
Q: Why did the first replay fail?
A: The model account ran out of money halfway. The tool still wrote a report then. Now it checks the models first and refuses a run with failed calls.
