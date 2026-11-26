# 30 — Recording the tree state when a run starts

**What**
Two evals now record the git tree state once, when the run starts. Before, they checked it while writing the report. By then their own output files could make the tree look changed.

**Why**
A report that says "dirty" looks like it ran on unsaved code. If the eval writes into the repo, it marks itself dirty. That makes a clean run look untrustworthy.

**Number**
No number yet. I will measure it in the memory rerun that follows.

**Trade-off**
A file edited during the run is no longer caught. Runs are short and use a separate checkout, so that risk is small. The full-graph evals already worked this way.

**Likely follow-up question**
Q: Why not write all outputs outside the repo?
A: Some reports must live in the repo, next to a CSV they link to. Recording the state at the start keeps both the link and an honest flag.
