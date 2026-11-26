# 30 — Saving rows so metrics can be re-scored

**What**
I made the memory eval and the context A/B save every row. Each run now writes the full transcripts or answers. It also records the code version, config hash and models. The memory report also names the real models now.

**Why**
I fixed two metrics, but I could not re-score the old runs. They kept only totals, so a fix meant paying for a new run. The memory report also showed "env" instead of model names.

**Number**
No number yet. I will measure it in the live rerun that follows.

**Trade-off**
Each run now stores more text on disk. The rows stay local and out of git. That is a small cost for being able to fix a metric for free.

**Likely follow-up question**
Q: Why not store rows from the start?
A: The first versions only needed the totals for their report. The metric bugs showed that totals hide what went wrong. Now every eval keeps its rows by default.
