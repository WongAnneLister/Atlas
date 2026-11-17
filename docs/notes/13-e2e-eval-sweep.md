# 13 — End-to-end evaluation, threshold sweep and hallucination review

**What**
I ran the real gate sweep and full conversation graph.
I added safe checkpoints so interrupted sweeps can continue.
I added failed question IDs to the reports and exported human review rows.

**Why**
The gate must reject questions without enough evidence.
Without real runs, safety and speed would remain guesses.
The lost SSH connection also showed why completed scores needed safe storage.

**Number**
I selected 0.17 from dev scores only.
The full graph accepted 3.33% of no-answer test questions.
That missed the zero-false-accept safety target.
It also rejected 26.67% of answerable test questions.
Source: eval/reports/baselines/e2e-001/e2e.md

**Trade-off**
I kept failed outcomes instead of rerunning only the bad cases.
Shared model resources and connection failures affected speed and missed answers.
I kept the selected threshold despite the test failure.

**Likely follow-up question**
Q: Why did a cited answer still fail the safety target?
A: Relevant payment text did not cover Cash App Pay.
The answer admitted uncertainty but still gave facts without creating a handoff.
I will study coverage on dev before a new measured change.
