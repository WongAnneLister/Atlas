# 28 — Same-day latency check

**What**
I ran the old 25b code and the current code on the same evening. Each ran alone, one question at a time. I compared both with the earlier 25b latency run.

**Why**
The review showed a five second rise in median latency. The new code made the same model calls with the same tokens. So I had to rule out a slower provider before I blamed the code.

**Number**
The same 25b code had a median of 9.98 seconds on Nov 22. On Nov 26 it took 15.17 seconds. On that evening, the current code took 11.84 seconds. So the rise came from the day, not from the code.
Source: eval/reports/context_regression.md

**Trade-off**
The two runs went one after the other. Provider speed can change within an hour. So I do not claim the current code is faster.

**Likely follow-up question**
Q: How would you make latency numbers trustworthy?
A: Compare only runs made the same day, back to back. Better, alternate old and new runs several times. Then provider drift hits both sides equally.
