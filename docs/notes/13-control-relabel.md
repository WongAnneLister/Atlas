# 13 — Fixing labels on my store controls

**What**
I marked 13 of my 40 store questions with a new flag. For them, an order lookup or a human is also a right route. I changed no question and no answer.

**Why**
A reviewer pointed at one of my examples. "When will my parcel arrive?" should check the order, not quote a policy. I had counted those routes as mistakes. That made the routing problem look bigger than it is.

**Number**
The build report now lists 13 items where another route is also correct. The other 27 still need a policy answer.
Source: eval/reports/store_controls.md

**Trade-off**
Changing labels after seeing results is risky. So I only touched a notes field, in its own commit. The builder refuses any other change to the frozen set.

**Likely follow-up question**
Q: Isn't relabelling after results a way to cheat?
A: It can be. I kept the questions and answers fixed. The commit says why each change was made. Anyone can compare the two versions.
