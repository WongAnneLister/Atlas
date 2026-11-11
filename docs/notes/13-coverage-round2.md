# 13 — Evidence coverage and clear failure reasons

**What**
I made the knowledge answer list each requested part and its source quotes.
Code checks the quotes and adds the citations.
Missing support now creates a real handoff.
I also separated model failures from missing evidence in evaluation records.

**Why**
The old code accepted a partial answer with any valid citation number.
A related payment policy could pass without answering the actual question.
Offering human help in text did not create a handoff record.
I kept the existing evidence check before this answer step.

**Number**
Answers to unanswerable questions fell from 1/30 to 0/30 on the regression set.
Rejected answerable questions rose from 10/120 to 11/120.
These draft labels still need human review.
I did not measure human-confirmed answer accuracy.
Source: eval/reports/coverage_round2_summary.md

**Trade-off**
I sent more questions to human support when any part lacked evidence.
That costs support time and can reject useful partial answers.
Longer structured responses can also increase model time and token use.
I kept original failures and labels visible in the comparisons.

**Likely follow-up question**
Q: Does finding the quote prove the answer is correct?
A: It proves the quoted text exists in the source.
The model can still misread it or miss part of the question.
Human review and broader tests remain necessary.
