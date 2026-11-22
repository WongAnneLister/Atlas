# 23b preparation — Validate frozen labels with policy history

**What**
I updated the check for the frozen evaluation labels.
I exclude only the historical policy sections listed in the version file.
I also check that each listed section is present.

**Why**
The new history made the corpus look different to the old check.
I wanted the check to catch edits to current policy text.
It still rejects any extra section outside the version file.

**Number**
No number yet. I will measure it in commit 23b.

**Trade-off**
The check now reads the version file when history is enabled.
The evaluation cache still uses its existing key.

**Likely follow-up question**
Q: What happens when policy history is disabled?
A: I compare the full corpus to the original record.
I use the same check as before.
