# 25 — Grounding review fixes

**What**
I gave every requested part its own check.
I made a quote from the wrong source fail only its claim.

**Why**
One question can ask for several things.
Losing a main claim could silently drop part of the answer.
A bad supporting quote can also affect a detail the customer never asked for.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
The whole route hands off when any requested part loses its main claim.
I can still keep a reply when only an extra detail fails.

**Likely follow-up question**
Q: What if the verifier skips a claim?
A: I require a verdict for every claim I sent.
If the response breaks that rule, I hand off the whole answer.
