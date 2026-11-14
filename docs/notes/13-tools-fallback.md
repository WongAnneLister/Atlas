# 13 — Sending general questions back from the order tools

**What**
Some general questions were routed to the order tools. If the tool model calls no tool, the question now goes to knowledge. It still has to pass the evidence gate and the coverage check. A failed order lookup still goes to a human.

**Why**
"Do you ship abroad?" has a policy answer. The order model could not answer it with tools. The old code then handed off, so a human got an easy question.

**Number**
No unanswerable question was answered through the new route on any test set. On dev, it rescued two or three good questions per run. Dev false rejects went from 20 and 26 to 15 and 16 out of 120. Identical runs already differ by 22 items, so that drop is not proven.
Source: eval/reports/tools_fallback.md

**Trade-off**
A question can now take one more model call before it ends. The order model's own text is thrown away, even when it looked fine. Account questions sent to the fixed reply path are still not fixed.

**Likely follow-up question**
Q: Why throw away the order model's answer?
A: It had no source behind it. The knowledge path quotes a source for every claim. A human still gets the question when no source is found.
