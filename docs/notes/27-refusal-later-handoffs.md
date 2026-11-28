# 27 — Any handoff after a refund refusal keeps the refusal

**What**
The refund-refusal score now ignores any handoff that comes after the refusal. Before, only a handoff the customer asked for was allowed. A handoff before the refusal still fails.

**Why**
After a correct refusal, one customer asked for an exception. No policy covers exceptions, so the agent passed it to a human. The refusal was right, but the chat failed.

**Number**
No number yet. I will measure it when the saved runs are re-scored next.

**Trade-off**
I changed this rule after seeing a failure, for the second time. I made the call as the author and wrote down why. The rule is now looser than before.

**Likely follow-up question**
Q: Could a looser rule hide a real failure?
A: The refusal must still happen first, with no refund created. Only what comes after it is ignored.
