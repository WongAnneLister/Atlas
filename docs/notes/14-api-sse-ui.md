# 14 — FastAPI chat stream and order picker

**What**
I built a browser chat that shows replies, sources, and handoffs.
I added an order picker that pauses and resumes a refund.
I linked each conversation to its demo customer.

**Why**
I wanted people to see the sources behind an answer.
I needed the refund flow to wait for a customer to choose an order.
I used a stream so the page could show progress while the workflow ran.

**Number**
No number yet. I will measure it in commit 15.
Source: No evaluation report for this commit.

**Trade-off**
I sent the checked answer in small pieces after it was ready.
That made the first piece arrive later.
It kept unchecked text off the page.

**Likely follow-up question**
Q: Why not stream real tokens?
A: The model returns structured data that the app must check first.
I waited for that check before showing any answer text.
