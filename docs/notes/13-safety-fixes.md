# 13 — Two safety fixes for unsupported answers

**What**
I added two checks after the chunking test showed wrong answers. First, an order answer must quote the tool data for each fact. A fact without a quote sends the question to the gated knowledge path. Second, each answer part now says if the source states it directly.

**Why**
The order-tool path skipped the evidence gate, so it could invent store rules. The gate is my check that evidence is strong enough to answer. Small chunks also let the model answer from what a source did not say. That is a guess, not a cited fact.

**Number**
With the new index, wrong answers on v1 fell from 5 to 0 of 106. The absence rule stopped 3 of them; the other 2 changed by noise. On v2 they fell from 1 to 0 of 35. Dev false rejects were 19 of 120 before and 25 and 18 after.
Source: eval/reports/safety_fixes.md

**Trade-off**
Both checks fail closed, so some good answers now hand off. The quote check itself errored in 14 of 32 checks. In those cases the model gave no structured reply. I accepted that, because an error leads to the gated path, not a guess.

**Likely follow-up question**
Q: Does the quote check hurt real order questions?
A: Probably yes, through its error rate. These sets ask policy questions, so I did not measure order questions here. Next I will retry once when the model gives no structured reply.
