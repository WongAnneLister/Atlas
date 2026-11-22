# 18a — Refresh the order audit after the database move

**What**
I re-seeded the local order database after commit 18.
I re-ran the order audit and saved its report.
Only the provenance lines changed: the commit, hashes and date.
Provenance means the record of where a number came from.

**Why**
Commit 18 added new settings, so the config hash changed.
The audit then refused the old database as out of date.
The saved report also pointed at an old commit.
Now the report matches the code on main.

**Number**
The audit still counts 300 orders and 749 order items.
It still blocks 900 cross-customer operations.
Every count is the same as before the move.
Source: eval/reports/archive/orders_seed-5fbeb90.md

**Trade-off**
The dataset hash changed, but the order data did not.
The hash covers the seed record, and that record stores the config hash.
A reader could think the data changed, so I say it here.
Any unrelated setting change will cause this again.

**Likely follow-up question**
Q: Why does an unrelated setting change the order audit?
A: The seed record hashes the whole config, not only the order settings.
I plan to hash only the settings that build the data.
That is already listed as a follow-up in my progress file.
