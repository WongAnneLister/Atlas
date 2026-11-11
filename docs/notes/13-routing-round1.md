# 13 — Policy guidance and order actions

**What**
I clarified how the agent chooses a path for each request.
General guidance now goes to document search.
Personal order actions still go to tools or the refund flow.
I added saved prompt comparisons and checks for these boundaries.

**Why**
The old prompt confused general questions with requests to perform actions.
Some answerable questions never reached document search.
I changed the guidance without changing evidence rules or question labels.

**Number**
Dev routing match rose from 80.00% to 98.33%.
Authored control match rose from 90.91% to 100.00%.
These numbers measure routing, not correct answers.
Source: eval/reports/routing_round1.md

**Trade-off**
More questions now reach document search and answer generation.
Those steps cost model calls and processing time.
I kept the evidence threshold unchanged.
I preserved failed calls instead of replacing them with successful retries.

**Likely follow-up question**
Q: Does better routing prove the answers are safe?
A: Routing only chooses the next step.
I still need evidence checks and human answer review.
I froze the candidate before running the full test set.
The same unsupported payment question still received an answer.
