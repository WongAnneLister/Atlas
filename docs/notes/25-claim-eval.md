# 25 — Claim evaluation

**What**
I split saved answers into claims and kept the sources cited for each part.
I built a review sheet so a person can label claims without seeing model verdicts.
I added scores for the verifier and kept constructed cases in a separate group.

**Why**
An answer can cite the right page and still give a wrong number.
I needed a way to measure mistakes inside an answer before adding a new check.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
The draft uses saved test answers while I wait for dev answers.
Human labels take time, so I also built cases with deliberate errors.
I report the two groups separately because they measure different things.

**Likely follow-up question**
Q: Why use the sources the answer already cited?
A: I want to know whether the cited text supports the claim.
Searching again could hide a bad citation.
