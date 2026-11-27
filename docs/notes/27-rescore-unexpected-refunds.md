# 27 — Re-scoring counts refunds nobody expected

**What**
The re-scoring tool now counts refund requests that the scenario did not expect. It needs no model call.

**Why**
A refund created by mistake costs the shop money. Task success alone hides it among other failures. My refund prompt rule needed this count as a safety check.

**Number**
No number yet. I will measure it when the prompt trial is re-scored next.

**Trade-off**
The count trusts the scenario labels. A wrong label makes a correct refund look unexpected. That is why I reviewed the refund labels first.

**Likely follow-up question**
Q: Why not block such refunds in the agent instead?
A: Each request already waits for human review. The count tells me how often the agent asks for one wrongly.
