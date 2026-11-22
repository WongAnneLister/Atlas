# 25 — Claim grounding

**What**
I added a check between answer writing and customer release.
I checked numbers in code and asked a model to verify the remaining claims.
Each claim used only the sources cited for its part.

**Why**
A valid citation can sit beside an invented detail.
I wanted to catch that detail before the customer saw it.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
The customer waits for the extra check before seeing an answer.
I remove unsupported details and hand off when the main point fails.
A quote proves where evidence came from. The model still judges what it means.

**Likely follow-up question**
Q: What happens when only part of an answer fails?
A: I can keep supported parts when partial answers are enabled.
I send the failed part to a human agent.
