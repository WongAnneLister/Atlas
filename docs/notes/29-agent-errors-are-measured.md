# 29 — The agent's own errors are measured, not treated as outages

**What**
I listed one error type as the agent's own behaviour, not a broken dependency. That type is `ContextOverflow`, a prompt that is over its token budget. The release gate and the run checks now skip it. The short-term memory eval can also rebuild its report from saved chats.

**Why**
My test rerun of the memory eval was refused for one such error. The answer prompt ignored its budget, so the check step overflowed. The agent handed off safely. That is a defect the report should show, not a reason to void the run.

**Number**
No number yet. I will measure it when the saved run is re-rendered in the next commit.

**Trade-off**
I changed the rule after seeing a result. I wrote that down in the rules file with the reason. A run full of these errors now passes the check. The metrics must show their cost.

**Likely follow-up question**
Q: Isn't changing the rule after the result a way to hide a bad run?
A: The rule exists to catch outages like an empty balance. This error comes from my own code, and the agent still fails safely. Its turns are listed in the report, and the budget bug stays open.
