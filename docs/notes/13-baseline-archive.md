# 13 — Freeze the first full evaluation baseline

**What**
I saved the first complete test run as a fixed comparison baseline.
I copied its reports, charts, settings, and local question results.
I recorded file checksums, unique values that reveal later file changes.

**Why**
Default report paths can change after another run.
Without a fixed copy, I could lose the starting point for later comparisons.
I documented the commands for comparing future runs against this baseline.

**Number**
The saved run had a 3.33% false-accept rate.
It also had a 26.67% false-reject rate.
These are acceptance outcomes, not verified answer accuracy.
Source: eval/reports/baselines/e2e-001/e2e.md

**Trade-off**
I kept full question text and answers local because source sharing rights remain limited.
A fresh clone includes reports but needs the local files for question-level comparisons.
I recorded connection failures and shared compute as limits on performance comparisons.

**Likely follow-up question**
Q: How will you make the next comparison fair?
A: I will keep the same questions, labels, and scoring rules.
I will record deliberate changes and use separate output files.
I will tune on dev and report test results without hiding failures.
