# 20b — One open refund request per item

**What**
I fixed the gap that my red-team baseline found.
Now an item can have only one refund request in review.
The database write refuses a second request for the same item.
The refund decision also skips items that already have a request.

**Why**
Before this, a customer could ask again in a new chat.
Each chat made a new review request for the same item.
Two human reviewers could then approve the same refund twice.

**Number**
No number yet. I will measure it in commit 20c.

**Trade-off**
Each refund write now locks the order row in Postgres.
So two chats about one order wait for each other.
That costs a little latency, but only on refund writes.
A customer with a real second problem must wait for the first review.

**Likely follow-up question**
Q: Why check in both the decision and the database?
A: The decision check gives the customer a clear handoff early.
But two chats can race past that check.
The database check runs under a lock, so it cannot be raced.
I tested that race on both SQLite and Postgres.
