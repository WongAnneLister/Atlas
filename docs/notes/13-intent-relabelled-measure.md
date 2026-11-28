# 13 — Intent accuracy on the relabelled holdout

**What**
I measured intent accuracy once on the relabelled holdout, with the current prompt. It is still below the 90% target. I sorted the remaining errors by cause.

**Why**
After relabelling, I needed to split the gap. Part is labels, and part is the classifier. Mixing the two would hide real classifier mistakes.

**Number**
Intent accuracy is 0.8000, and it still misses the configured target. Path accuracy is 0.8071.

Source: eval/reports/intent.md

**Trade-off**
My review only covered the 85 items the text rule flagged. Some how-to questions with odd wording still carry topic labels. So part of the remaining gap is still labels, not the model.

**Likely follow-up question**
Q: So is the classifier good enough now?
A: Not yet. I must finish the label review before I can say what the classifier really scores.
