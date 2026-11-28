# 13 — Intent labels now follow the routing rule

**What**
I reviewed 85 intent questions that a text rule flagged as possibly informational. I moved 65 of them to the policy intent and kept 20. The model drafted each decision with a reason, and I approved them.

**Why**
The old labels followed topic. So "how do I change my address" counted as a shipping action. My routing sends such how-to questions to the policy path on purpose. The holdout and the router disagreed by design.

**Number**
No number yet. I will measure it on the relabelled holdout next.

**Trade-off**
I changed labels after seeing a low score, which risks bias. To limit that, the flagging rule never looked at model predictions. Kept labels are listed too. The rule may still miss odd phrasings.

**Likely follow-up question**
Q: Did you just relabel the questions the model got wrong?
A: No. The rule flagged questions by wording alone, right or wrong. Twenty of them kept their old label.
