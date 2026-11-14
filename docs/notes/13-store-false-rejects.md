# 13 — Does the store filter block good answers?

**What**
I tested the store filter off and on. I used fresh answerable questions and the dev set. I ran each setting twice. Two runs of the same setting show how much the model changes by itself.

**Why**
A filter that stops wrong answers can also hide right ones. My earlier tests only had unanswerable questions. They could not show extra handoffs.

**Number**
On dev, no answerable question was lost in both filter runs. The right page stayed in the top five every time. On the new store questions, one of 40 was lost in both runs. It had passed before only because of an unrelated Flipkart page.
Source: eval/reports/store_false_rejects.md

**Trade-off**
Running everything twice doubled the time to about two hours. The noise is large, so small rate changes mean little. Many good questions still fail earlier, at routing.

**Likely follow-up question**
Q: Why not just report the false reject rate?
A: The rate moved by up to seven items between identical runs. So I counted questions lost in both runs. Then I checked why each one changed.
