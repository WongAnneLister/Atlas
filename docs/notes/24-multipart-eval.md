# 24a — Testing multi-part questions

**What**
I built an evaluation set for questions with two parts.
I added checks for complete answers, partial answers, and referrals to a human.
I also reviewed saved runs for questions needing more than one document.

**Why**
I wanted to learn where the old system lost part of a question.
I needed examples where only one part has an answer.
Those examples help me check whether a partial reply stays safe.

**Number**
In the full test run, the system accepted 23 of 30 cross-document questions.
Six of the seven rejections happened before knowledge search.
Source: eval/reports/cross_doc_failures.md

**Trade-off**
I combined existing questions, so this set may read differently from real chats.
The saved results give little evidence that separate searches will fix the main problem.
I will test that with paired runs after the planner is built.

**Likely follow-up question**
Q: When does a partial answer count as a safety failure?
A: If neither part can be answered, replying to either one counts as a failure.
I still count a partial reply separately from a complete reply.
