# 27 — Each simulated chat starts with clean order data

**What**
The simulator now refuses to start if the orders database already holds refund requests. It also removes the requests each chat creates. A refusal still counts as correct if the customer then asks for a human.

**Why**
All three refund scenarios scored zero. One cause was a leftover refund request in the dev database. The agent rightly refused to refund the same item twice. Another cause was a scoring rule that failed any handoff after a correct refusal.

**Number**
No number yet. I will measure it in the refund evidence that follows.

**Trade-off**
Each chat now starts from fresh order data. So no chat can test a request left by another. I also changed a scoring rule after seeing failures. I wrote down the reason in the code.

**Likely follow-up question**
Q: How did a refund request get into the dev database?
A: A run on November 23 wrote to it directly. I removed the row with the owner's approval. The simulator now fails if it finds one.
