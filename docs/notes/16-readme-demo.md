# 16 — English README, generated results and demo script

**What**
I rewrote the README for a reviewer who has three minutes.
A script reads the eval reports and writes the results table into the README.
I also wrote a two-minute demo script and checked every step on the running app.

**Why**
A hand-typed number can drift away from the report it came from.
Now the table is rebuilt with one command, and a test fails on stale numbers.
Another test fails if a percentage appears outside the generated table.

**Number**
The README shows a test false accept rate of 0.00%.
That means no unanswerable test question got an answer.
The cost of that safety is a false reject rate of 21.67%.
Source: eval/reports/archive/e2e-6cf0e48.md

**Trade-off**
The README can only say what the reports say, so some rows look weak.
The demo refund step ends in a handoff, not a cited decision.
I kept it that way instead of hiding it or changing code for the video.
Prose cannot quote numbers, so the design notes point to tables instead.

**Likely follow-up question**
Q: Why does the refund demo hand off instead of deciding?
A: The refund flow builds its own policy search query from order fields.
That query matches the policy text badly, so the gate score stays low.
The gate then hands off, which is the safe result.
Next I will fix that query and measure it on the eval set.
