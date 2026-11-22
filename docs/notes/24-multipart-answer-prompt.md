# 24 — Multipart answer prompt rules

**What**
I copied the evidence rules from the single-question prompt into the multipart prompt.
I kept separate instructions for how the model reads and returns each part.
I added a test that checks each shared line word for word.

**Why**
The multipart prompt had dropped rules about missing evidence and similar products.
It also dropped rules about time limits and eligibility.
Those limits can change what a customer expects.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
I kept two prompt files because they describe different input and output.
Edits to shared rules now need to go into both files.
The test catches missing lines, and live evaluation checks how the model follows them.

**Likely follow-up question**
Q: Can the system still answer one part and hand off another?
A: Yes. The graph checks each part against its own sources.
It can show the supported answer and hand off the unsupported part.
