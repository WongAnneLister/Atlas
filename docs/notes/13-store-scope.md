# 13 — Store-scope check

**What**
I made a question about one store see only that store's documents. Product manuals stay visible to both stores. I take ten ranked results, remove the other store, and keep the top five.

**Why**
The bot answered generic-store questions with Flipkart rules. The prompt told it not to, but it did anyway. A rule in code is more reliable than a request in a prompt.

**Number**
On the fresh cross-store set, false accepts fell from 17/35 to 0/35. On the older near-miss set, they fell from 13/106 to 4/106. Old test false rejects rose from 24/120 to 33/120. My script traced none of those changes to the filter.
Source: eval/reports/store_scope.md

**Trade-off**
The check only sees store names written in the question. A follow-up turn depends on the rewrite keeping the name. The refund path is not scoped yet.

**Likely follow-up question**
Q: How do you know the extra rejects are noise?
A: I compared the evidence before and after. None of those questions had other-store evidence to remove. Their routes or answers changed between two runs of the same model.
