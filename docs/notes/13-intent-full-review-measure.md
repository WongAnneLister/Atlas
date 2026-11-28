# 13 — Intent accuracy after a full label review

**What**
I measured intent accuracy once on the fully reviewed holdout. Every label now follows the routing rule. The remaining errors are the classifier's own.

**Why**
Until every label followed the rule, the score mixed label noise with model errors. Now the gap to the target is a real classifier gap.

**Number**
Intent accuracy is 0.8619 and path accuracy is 0.8690. Both still miss the configured target.

Source: eval/reports/intent.md

**Trade-off**
I could tune the prompt on these errors. But then this set would stop being a fair test. Tuning must use the routing dev set instead. That is slower but keeps this score honest.

**Likely follow-up question**
Q: What are the main remaining mistakes?
A: Permission questions about swaps go to the exchange intent. Refund tracking goes to the order intent.
