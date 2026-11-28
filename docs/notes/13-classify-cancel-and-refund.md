# 13 — "Cancel and refund" goes to the refund path

**What**
I added one line to the intent classifier prompt. A request to cancel an order and get the money back is a refund request. Cancelling without asking for money stays an order request.

**Why**
A customer asked to cancel a shipped order and get a refund. Two of three times, the classifier picked the order intent. The order tools cannot cancel, so those chats never reached the refund decision.

**Number**
No number yet. I will measure it in the intent and refund runs that follow.

**Trade-off**
No eval item asks to cancel and refund, so dev cannot show the gain. The intent eval only guards against harm here. The evidence for the fix comes from one test run.

**Likely follow-up question**
Q: Why not add a cancel tool instead?
A: Cancelling a shipped order is a policy decision. The refund path already checks the policy and hands it to a human.
