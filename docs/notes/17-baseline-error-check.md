# 17b — Baseline promotion refuses runs broken by errors

**What**
I made baseline promotion check for dependency errors first.
A dependency is a service the agent needs, like the model API or Milvus.
If too many questions hit such an error, promotion stops with a clear message.

**Why**
My first smoke run failed because the model account had no money left.
Every question was handed to a human, so there were no false accepts.
The old check only looked at false accepts, so it would have saved this run.
Every later run would then look like a big improvement against a broken baseline.

**Number**
No number yet. I will report the first real baseline after a clean smoke run.
A new test feeds a run where every question failed the model call.
Promotion accepted that run before the fix and refuses it now.

**Trade-off**
I allow a small share of errors, set in the gate rules file.
Earlier full runs had a few malformed model replies.
Zero tolerance would block almost every baseline for that reason.
The cost is that a baseline can hold a few failed questions.

**Likely follow-up question**
Q: Why not retry the failed questions instead of refusing the run?
A: The eval already retries some calls.
A dead account or a closed tunnel will not fix itself on retry.
Refusing makes the person fix the cause and collect a clean run.
