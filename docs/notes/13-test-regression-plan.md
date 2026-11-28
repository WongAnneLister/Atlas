# 13 — Plan for a full test regression

**What**
I wrote down the test runs before running them. One run covers the 150 test questions end to end. The other runs all 30 test chat scenarios three times.

**Why**
Many parts changed since the last full test run. The headline numbers in the README are now old. Writing the plan first stops me from picking runs after seeing results.

**Number**
No number yet. I will measure it in the next commit.

**Trade-off**
One run per test is cheap but noisy. Latency cannot be compared, because the old runs used a remote database.

**Likely follow-up question**
Q: What if the new run is worse?
A: I report it as measured. I do not tune anything on the test split.
