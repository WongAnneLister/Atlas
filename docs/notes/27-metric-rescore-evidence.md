# 27 — Re-scoring saved chats with the fixed metric

**What**
I re-scored two saved simulator runs with the fixed fact-retention metric. I made no model calls. The report records each run's file hash and the metric code version.

**Why**
An earlier report said fact retention fell from 16.67% to zero. That drop was used to justify the next feature. I had to check whether the drop was real.

**Number**
The earlier baseline reached one of six recall checkpoints, and that one was retained. The next run reached none of six. So retention was not measurable in either run. Task success was unchanged by the fix.
Source: eval/reports/sim_rescore.md

**Trade-off**
The transcripts stay on my machine, so others need the same files to repeat it. The file hashes let them check that. Fixing the simulator so it reaches the recall turn is separate work.

**Likely follow-up question**
Q: Does this mean the memory feature was useless?
A: No. It means these runs could not show its effect either way. To measure it, the simulated user must reach the recall turn.
