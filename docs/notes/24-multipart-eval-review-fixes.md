# 24 — Multipart eval review fixes

**What**
I matched planned parts to the expected parts before scoring them.
I balanced which part comes first in questions with one answerable part.
I used the item's answerability label to count answers on unsupported questions.

**Why**
The planner can drop a greeting or connector when it rewrites a question.
Exact text matching could mark a correctly cited answer as wrong.
Balanced order lets me test handoffs in either position.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
I match by position when the counts agree.
That assumes the planner kept the order.
When the counts differ, I use shared words and can miss a larger rewrite.

**Likely follow-up question**
Q: Can one planned part get credit for two expected parts?
A: I let each planned part match at most one expected part.
A full answer still needs the right citations for every expected part.
