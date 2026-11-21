# 22 review fix — Release without blocking the database

**What**
I moved the index release check out of the registry lock.
The registry is the table that records which index serves customers.
Now the check runs first, and the switch takes the lock afterwards.
I also fixed garbage collection and the heading experiment.

**Why**
The release check can take an hour on a CPU.
The registry shares its database with orders and refunds.
On SQLite, the lock blocked every refund write for that hour.
The experiment fix matters too: a committed report could no longer be rerun.

**Number**
No number yet. I will measure it in commit 22b.
I added five tests, and each one failed before the fix.

**Trade-off**
Another release can now finish while my check is still running.
So the switch checks that the serving index did not change.
If it changed, I refuse and ask for fresh evidence.
That wastes one check, but it never blocks customers.

**Likely follow-up question**
Q: Why not just use a separate database for the registry?
A: That would also stop the blocking.
But it adds a second database to run and back up.
A short lock solves the real problem with less setup.
