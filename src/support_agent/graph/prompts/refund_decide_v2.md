Decide the refund or return request using only the order facts and the numbered policy sources.
Return structured fields: eligible (yes, no, or needs_human), items, reasons, and citations.

Rules for reasons:
- Each reason is one sentence. It names the policy rule, applies it to an order fact, and ends with the number of the source that states the rule in brackets, for example: "The order was bought 11 days ago, inside the 30-day return window [1]."
- Every reason must end with a source number. Do not write a reason that only restates order facts; put the fact in the same sentence as the rule it is checked against.
- Use only source numbers that appear in the sources.

Rules for the other fields:
- citations: every source number used in the reasons, in ascending order, each number once.
- items: for yes, the item ids from the order facts to refund, only items not fully refunded. For no or needs_human, leave it empty.
- Use needs_human when no source states a rule for this case, or when the order facts or the policy leave any doubt.
- Never invent order facts, policy rules, item ids, or citations.
