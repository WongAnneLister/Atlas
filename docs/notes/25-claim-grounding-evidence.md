# 25b — Claim grounding evidence

**What**
I measured the claim check with real models. I ran it on a frozen claim set. Then I compared full runs with the check off and on. I also ran the release gate, a red-team smoke test and a latency test.

**Why**
Commit 25 had only fake-model tests. I needed to know if the check catches invented details. I also had to know how many good answers it wrongly cuts.

**Number**
On test, the check caught all 60 constructed false claims. It flagged none of 145 claims drafted as supported. With the check on, eval_v1 false rejects went from 12 to 16 of 120. P95 latency rose from 19.1 to 22.5 seconds.
Source: eval/reports/claim_grounding.md

**Trade-off**
Real-claim labels are drafts from a model, not yet reviewed by the author. The check missed five drafted false claims, mostly an extra "Yes". Two good answers were cut by mistake.

**Likely follow-up question**
Q: Why trust numbers from model-drafted labels?
A: I only trust the constructed claims fully. The real-claim numbers stay provisional until the author reviews a sample. The saved verdicts can be rescored without new model calls.
