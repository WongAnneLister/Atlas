# 20 — A test set for unsafe replies

**What**
I built a red-team test set: attacks that try to make the agent unsafe.
The attacks use common tricks, like fake system notes and role-play.
I used fake orders and planted markers to spot leaks.
I tested the harness with fake models through the chat API.

**Why**
I wanted a fixed test before adding new safety checks.
I needed to see when the agent crossed an account boundary.
I also wanted to catch promises the policy could not support.

**Number**
No number yet. I will measure it in commit 20a.

**Trade-off**
I used fake customer data to protect real records.
A fake case can miss patterns from real customer chats.
Many cases share templates, so the error bars look tighter than they are.
I left the model judge results open for human review.

**Likely follow-up question**
Q: How do you tell when a test case catches an unsafe reply?
A: I check for evidence like a matching refund row or a private marker.
I use a model judge to compare promises with cited policy.
A person still needs to review those judgments.
