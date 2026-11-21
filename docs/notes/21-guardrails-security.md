# 21 — Guardrails and signed demo sessions

**What**
I bound each chat to a signed token for the selected demo account.
I checked each message before rewriting and each reply before sending.
I limited request rates and masked private details in logs and traces.

**Why**
Before this, the API trusted the customer id in the request body.
Anyone could act as any customer.
A model can also be talked into repeating private text.
So the checks that matter most run in code, not in the model.

**Number**
No number yet. I will measure it in commit 21b.

**Trade-off**
Simple rules can miss a risky reply or block a useful one.
I kept the optional model check off to avoid adding calls.
I will measure normal questions as well as unsafe outcomes.

**Likely follow-up question**
Q: Does the token prove who the person is?
A: I sign it to bind a chat to one demo account.
Anyone can still request a token for a listed demo customer.
A real service needs a separate sign-in step.
