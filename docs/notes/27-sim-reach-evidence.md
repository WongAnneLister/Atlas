# 27 — Evidence that the simulator now asks its recall questions

**What**
I ran the old and fixed simulator on eight dev chats with recall checkpoints. I re-scored all runs with the same metric code. I did not run or read the test scenarios.

**Why**
Fact retention was the reason for two memory features. It had never been measured, because the recall questions were not asked. I needed proof that they are asked now.

**Number**
Before the fix, the chats reached 1 of 12 checkpoint turns. After it, they reached all 12. Fact retention on real recall probes was 80.00% across 5 scenarios. The interval is wide.
Source: eval/reports/sim_rescore.md

**Trade-off**
Five checkpoints still cannot be scored, because their script names the answer. Eight dev chats are a small sample. The test reports still use the old simulator.

**Likely follow-up question**
Q: What did the working probes reveal?
A: Asked "which order were we discussing?", the agent sometimes failed. It called an order tool without an ID and handed off. That is a real bug to fix next.
