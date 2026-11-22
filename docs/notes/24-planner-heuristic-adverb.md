# 24 — Planner pre-check and "and also"

**What**
I fixed the cheap check that decides whether to call the planner. It now accepts "and also" or "and then" before a second question. I added three test cases, and two failed before the fix.

**Why**
A live run on three dev questions never called the planner. Each question joined two requests with "and also". The rule expected a question word right after "and", so the extra word hid it.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
The check now sends a few more single questions to the planner. Each one costs one extra fast model call. The planner still decides whether to split, so the route does not change by itself.

**Likely follow-up question**
Q: Did you tune this rule on the benchmark?
A: I fixed it to match the written rule: a conjunction between two clauses. I found it on dev questions, and I did not look at test.
