# 13 — A patient retry policy for the simulated customer

**What**
I gave the simulated customer its own retry settings. It now tries six times and waits up to 30 seconds. The agent keeps its own quick retries.

**Why**
One network drop stopped a 30-minute test run with no report. The simulator had borrowed the agent's policy, which gives up in under two seconds. A tool that drives the test should wait out a short outage.

**Number**
No number yet. I will measure it in the next commit.

**Trade-off**
A long outage now stalls the run for a few minutes before it fails. The agent side is unchanged, so its errors still show up in the run checks.

**Likely follow-up question**
Q: Why not give the agent the same patient policy?
A: A customer is waiting on the agent. Long waits there would hurt latency.
