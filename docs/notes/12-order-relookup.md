# 12 — Re-reading the order when the customer does not repeat its ID

**What**
I gave the order path one retry for a common follow-up. Sometimes the model replies from order data it read in an earlier turn. It then gets one reminder to look the order up again first. A second reply without a lookup still hands off.

**Why**
Asked "which order were we discussing?", the bot handed off with a tool error. The model knew the order ID from the chat. But replies use only this turn's lookups. This turn had none.

**Number**
No number yet. I will measure it in the dev simulator rerun that follows.

**Trade-off**
The retry costs one more model call on those turns. The data still comes only from a fresh, customer-scoped lookup. So the reply can never use stale or another customer's order data.

**Likely follow-up question**
Q: Why not just reuse the order data from the earlier turn?
A: The order may have changed since then, for example a refund or a delivery. A fresh lookup costs little. It keeps every reply tied to data read in the same turn.
