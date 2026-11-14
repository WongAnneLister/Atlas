# 13 — A fresh near-miss holdout for false accepts

**What**
I wrote 106 new questions that the knowledge base cannot answer.
Each one sits close to real content, like a fake model number.
A script checks that each key phrase is missing from its source scope.
I froze the set before any gate change touched it.

**Why**
The old test set has only 30 unanswerable questions.
I had already looked at it three times, so it is no longer blind.
Most old unanswerable questions are far from the documents.
The one real miss, Cash App Pay, was a close neighbour of real content.

**Number**
The build report records 106 frozen items.
It also counts 21 closed-list items, explained below.
I have not measured the agent on this set yet.
Source: eval/reports/holdout_near_miss.md

**Trade-off**
I wrote these questions myself, so they may share my blind spots.
A missing phrase does not prove the meaning is missing.
The set has no answerable questions, so it cannot measure false rejects.
I still need a human to review every item.

**Likely follow-up question**
Q: What is a closed-list item?
A: A source lists accepted payment methods, and the question names another one.
Some reviewers would call that list a clear no.
I report those 21 items separately, so nobody has to trust my label.
