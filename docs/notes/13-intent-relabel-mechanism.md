# 13 — Author labels for the intent holdout survive a rebuild

**What**
I added a file of author-reviewed intent labels, keyed by item id. The build applies them after it picks the questions. An empty file rebuilds the same set, byte for byte.

**Why**
The holdout labels follow topic, but routing follows informational versus operational work. I am reviewing the disputed items by hand. Editing the built file directly would be lost on the next rebuild.

**Number**
No number yet. I will measure it after my review is applied.

**Trade-off**
The label file is one more input the loader checks. Any edit to it forces an explicit rebuild. That is the point, but it adds a step.

**Likely follow-up question**
Q: Why apply labels after selection, not before?
A: Selection balances questions per intent. Relabelling first would pick different questions, and the sets would no longer compare.
