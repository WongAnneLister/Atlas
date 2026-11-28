# 09 — Graph skeleton, query rewrite, and intent evaluation

**What**
I built a graph with fixed steps and routes.
I added question rewriting and structured intent labels.
I tested routing with fake models and saved conversation state.

**Why**
I wanted model errors to stay inside a known workflow.
I kept path selection in code.
I marked uncertain predictions for later evidence checks.

**Number**
I measured intent accuracy at 0.9048 across 420 questions.
I routed 0.9095 of questions to their expected path.
I recognized 0.7200 of labeled refund requests.
Source: eval/reports/archive/intent-6cf0e48.md

**Trade-off**
I used draft labels to get an early baseline.
Some source labels mix general questions with requests for action.
My return examples came from the same model provider.
Human review remains necessary.

**Likely follow-up question**
Q: What would you improve first?
A: I would review refund and human-contact mistakes first.
I would keep these held-out results unchanged.
I would test prompt changes on separate development examples.
