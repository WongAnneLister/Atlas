# 21a — Identity checks and look-alike questions

**What**
I froze a new set of checks for the agent.
I added fake account cases and normal questions that sound suspicious.
I kept the old cases so I can still compare them.

**Why**
I needed to measure whether a request could cross an account boundary.
I also needed to spot real questions that a new rule might block.

**Number**
No number yet. I will measure it in commit 21b.

**Trade-off**
I used fake accounts to keep the test away from real records.
I chose fixed examples, so the results cover those examples.

**Likely follow-up question**
Q: Why report blocked support questions separately?
A: A blocked support question is a cost to the user.
I measure that cost separately from unsafe replies.
