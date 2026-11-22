# 23a — Testing which policy applies

**What**
I added test questions for policies that change over time.
I wrote older versions of the return and price rules for the test.
I added fake orders with different dates for the two sets.

**Why**
A search can find the right topic and still find the wrong rule.
I wanted to catch that mistake before adding date filters.
A refund should use the date from the order record.

**Number**
No number yet. I will measure it in commit 23b.

**Trade-off**
I used one refund case per order date.
I kept price changes in general questions because refund search asks about returns.
It leaves other stores and policy changes untested.

**Likely follow-up question**
Q: What if a customer claims they bought it in August?
A: I label general policy questions with today's rule.
For refund questions, I use the date from the stored order.
