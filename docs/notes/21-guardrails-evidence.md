# 21b — Guardrail before/after evidence

**What**
I ran the same three evals before and after the guardrails commit.
They were the full red-team test split, its CI subset, and the knowledge smoke set.
I compared each case with its own earlier result.
Then I ran the release gate on the new runs, and it passed.

**Why**
Commit 21 added many defences but had no numbers yet.
A defence that does not move a metric is just extra code.
I also had to check that normal questions were not blocked.

**Number**
Spoofed identity attacks worked in 8 of 8 cases before the fix.
After the fix, they worked in 0 of 8.
Across all 72 paired attacks, the success rate dropped to 0.
Normal look-alike questions were wrongly blocked 0 of 15 times, before and after.
Source: eval/reports/guardrails_redteam_compare.md

**Trade-off**
The reply now streams only after the output check passes.
So the user sees no text until the whole answer is ready.
The knowledge smoke set showed no rise in total latency.
The bigger gap is the test itself: other attack types were already at zero.

**Likely follow-up question**
Q: If those attacks already failed, why keep the input guard?
A: It is a second layer of defence.
Today the evidence gate stops these attacks, because they find no matching policy.
A new attack might pass the gate, and the guard can still catch it.
I need a harder attack set to put a number on that.
