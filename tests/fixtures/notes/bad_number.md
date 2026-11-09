# 03 — Bad number

**What**
I merged FAQs into long policy documents. Each document covers one topic.

**Why**
Short FAQs do not test chunking. Long documents do.

**Number**
Recall at 5 reached 0.99 on the dev set. That beat the target.
Source: eval/reports/retrieval.md

**Trade-off**
Merging loses some FAQ structure. I keep the FAQ id on each section.

**Likely follow-up question**
Q: How did you merge them?
A: I grouped FAQs by topic. Then I ordered them by question type.
