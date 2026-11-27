# 35 — Every multi-turn and memory eval refuses a broken run

**What**
I extended the broken-run guard to four more evals. These are the context, short-term memory, long-term memory and prefix-cache experiments. Each arm is checked on its own. A refused run keeps its rows, writes no report, and exits with code 3.

**Why**
These evals still wrote normal reports when model calls failed. One dead arm could also hide among healthy arms. In the long-term memory eval, a failed memory extraction stored nothing in silence. Then "memory on" looked just like "memory off".

**Number**
No number yet. I will measure it in the next live rerun of these evals.

**Trade-off**
A short outage in one arm now voids the whole experiment. I must collect it again, and that costs model calls. A report built on failed calls would cost more trust.

**Likely follow-up question**
Q: Were your earlier memory results broken by this?
A: I don't think so. In that rerun, memory was loaded on 10 of 10 recall cases. So extraction worked there. The older runs were not checked with the new rule.
