# 12 — A v4 refund prompt explains policy validity dates

**What**
I added a v4 refund decision prompt. It is v3 plus one rule: a policy covers orders placed inside its validity dates. That holds even when today is later. The default is still v3.

**Why**
Under v3, an order bought under the old 90-day policy went to a human. The model saw that the policy ended on September 1 and treated it as expired. The order was placed before that date, so the old policy applies.

**Number**
No number yet. I will measure it in the dev runs that follow.

**Trade-off**
I found this on a test scenario, so the fix is shaped by test. The adoption decision still uses dev only. I state that in the decision rule.

**Likely follow-up question**
Q: Why not fix the date logic in code instead?
A: Retrieval already picks the policy by order date in code. The model still misread the dates. The prompt has to say what they mean.
