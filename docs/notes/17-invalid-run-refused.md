# 17 — Broken runs get no report

**What**
I made the full-graph and multipart evals refuse broken runs. They now use the same rule as the release gate. Too many dependency errors means no report and no run pointer. The script exits with a non-zero code.

**Why**
A missing model package made every item fail. The graph fell back to a template reply. The eval still wrote a normal report and exited with success. Those numbers looked like a real result.

**Number**
No number yet. I will measure it in the next regression run.

**Trade-off**
A run with a short outage now has to be collected again. That costs time and model calls. A wrong report costs more, because someone may trust it.

**Likely follow-up question**
Q: Doesn't the release gate already catch this?
A: The gate checks only the smoke run. The full evals feed reports and comparisons too. So they need the same guard at the point where they write.
