# 16a — Refund policy query

**What**
I rewrote how the refund flow searches for its policy.
It now asks one question in the store FAQ's own words.
Code picks the question from order facts, like final sale or coupon.
The query names the store, so other stores' rules are filtered out.

**Why**
The old query joined labels like "refund_request" with product categories.
It looked nothing like the policy text, so the reranker scored it low.
The evidence gate then handed off almost every refund.
So the demo could never show a refund decision.

**Number**
I ran both queries on all 300 mock orders, without any LLM.
The old query passed the gate for 47 of 300 orders.
The new query passed for 300 of 300, all from the right store.
Source: eval/reports/refund_policy.md

**Trade-off**
The five questions are hand-written, and they assume one store sells every order.
There is no held-out order set, so this is not a blind result.
Decisions still go to a human, because some reasons lack a citation.
I kept that strict check instead of loosening it for the demo.

**Likely follow-up question**
Q: Does passing the gate mean the refund decisions are right?
A: No. The gate only says the policy evidence is strong.
The decision model and code checks come after it.
I have not measured decision quality yet; that is the next step.
