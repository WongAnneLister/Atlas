# 05 — A fixed question set and human review

**What**
I built a question set before adding search code. I linked expected answers to source sections. I added checks and a human review sheet.

**Why**
A search system needs fixed questions before I tune it. I kept similar questions on the same side of the split. That helps keep test results separate from tuning.

**Number**
I built 300 questions with 240 answerable cases. Each group has 30 tuning questions and 30 separate test questions. Human review remains at 0/300.
Source: eval/reports/eval_set.md

**Trade-off**
No external drafting model was configured. I used fixed question templates and real source text. Similar model questions cover only a small product family. I kept every question unreviewed.

**Likely follow-up question**
Q: Does passing the validator mean the questions are correct?
A: No, the checks only catch clear data problems. A human must check meaning and source support. I left every review flag false.
