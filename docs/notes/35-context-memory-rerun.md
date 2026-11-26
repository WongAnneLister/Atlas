# 35 — Rerunning the cache and memory evals

**What**
I reran the cache strategy test and the long-term memory test with the fixed metrics. Both now save every row. I also fixed a cache arm that showed a made-up zero.

**Why**
Both old reports rested on broken metrics. One claimed memory raised recall from zero to ten of ten. The other compared against a "no cache" arm that was really cached.

**Number**
With memory on, the reply used the stored fact in 1 of 10 cases. With memory off, it was also 1 of 10. The memory reached the prompt in all 10 cases.
Source: eval/reports/memory_long.md

**Trade-off**
These results remove two headline claims from the README. Six test chats per arm are too few to rank task success. Memory needs questions that the evidence gate lets through before it can help.

**Likely follow-up question**
Q: Why keep a memory feature that shows no effect?
A: It is off by default, and it leaks nothing. The test questions mostly hit the evidence gate first. I would redesign the scenarios before deciding to drop it.
