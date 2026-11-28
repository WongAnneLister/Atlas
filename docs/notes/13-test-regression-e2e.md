# 13 — Full test regression, end-to-end half

**What**
I ran the whole graph on the 150 test questions at the current code. I compared it with the last two test runs. The simulator half is not done yet.

**Why**
Many parts changed since the headline numbers were made. The README still showed old results. A fresh test run shows where the agent really stands now.

**Number**
False reject fell to 9.17%, which is 11 of 120. No-answer false accepts stayed at 0 of 30. Recall at 5 is 0.9833.

Source: eval/reports/e2e.md

**Trade-off**
One run is noisy, and the paired change against the last run is not significant. Latency cannot be compared with older runs. Two good answers were blocked by the output guard.

**Likely follow-up question**
Q: Why is the simulator result missing?
A: The network to the model provider kept dropping. My run checks refused those runs, so nothing was reported.
