# 17 — Eval platform and release gate

**What**
I gave each evaluation set a version and a file hash. I saved each run in a common format. I added a release check for wrong answers and drops in quality.

**Why**
A few changed answers can make a score move by chance. I compare answers to the same questions to measure that uncertainty. The release check can catch a drop before it reaches main.

**Number**
The saved test run accepted zero of 30 questions with no answer. Wilson's method put the upper limit at 11.4 percent.
Source: eval/reports/archive/e2e-6cf0e48.md

**Trade-off**
I kept the question and answer files local. That means the hosted check needs a runner with the data. I still need human labels to measure agreement with the judge.

**Likely follow-up question**
Q: Why block even one wrong answer on the smoke set?
A: Each smoke question with no answer should be sent to a person. A single false accept breaks that rule. Zero observed errors still leaves uncertainty.
