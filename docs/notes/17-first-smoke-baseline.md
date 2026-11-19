# 17c — First smoke baseline on main

**What**
I ran the full agent on the fixed smoke set on a clean main.
The smoke set is a small, frozen group of test questions.
I saved that run as the baseline that every later run is compared with.

**Why**
The release gate had no baseline, so it could not compare anything.
Without it, the gate only stopped with a "no baseline" message.
Now a later run fails the gate if it gets significantly worse.

**Number**
The agent answered 0 of 30 questions that have no answer in the documents.
It wrongly handed off 5 of 40 answerable questions.
Two of 70 questions hit a dependency error, under the allowed limit.
Source: eval/baselines/main.json

**Trade-off**
This baseline is one run, and the model is not fully repeatable.
A few answers can change between runs with no code change.
The paired test reduces that risk, but it does not remove it.
My first attempt failed because the model account ran out of money.

**Likely follow-up question**
Q: How do you know the baseline itself is healthy?
A: Promotion checks the branch, a clean tree and the exact commit.
It also refuses runs with too many dependency errors.
My first broken run showed why that check was needed.
