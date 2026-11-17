# Demo script (2 minutes)

A script for the human who records the demo video.
Every message below was sent on the running app on 2026-11-17.
The setup was `make serve` with the VPS Milvus index `support_chunks`, threshold 0.15, and `deepseek-flash` through the relay endpoint.
The outcome next to each step is what the app did then.

## Before recording

- Start the app with `make serve` and open `http://127.0.0.1:8000`.
- Pick **Demo Customer 0001 (CUST-0001)**. Tick **Debug**.
- Send one warm-up question off camera. The reranker loads on the first question, which is slow.
- Click **New chat** before every step. A handoff earlier in the same chat can change how the next message is classified.
- If a reply is "I can help with shopping and after-sales questions...", the classifier returned no label.
  Click **New chat** and send the same message again. This happens with the current model; it is a known issue.
- Answers are not identical between runs. A knowledge step can also end in a handoff. If that happens, record it again.

## Script

| Time | Do | Say | Point at |
|---|---|---|---|
| 0:00 | Show the empty chat page. | "This is an after-sales support agent. It answers with citations, and it hands off to a human when the evidence is weak." | The page title and the customer picker. |
| 0:15 | New chat. Send: `What is the return policy on Flipkart?` | "A policy question goes to retrieval, then the evidence gate, then the answer." | The answer with citation chips [1]-[3] and their source headings. In Debug, the gate `score` and `passed: true`, and the trace `rewrite, classify, retrieve, gate, answer`. |
| 0:45 | New chat. Send: `How many heat and speed settings does the BHD340/10 have?` | "Model numbers need an exact match. BM25 finds the exact number; the reranker puts it first." | The answer "6 heat and speed settings" with one chip, `Catalog Hair Dryers > Philips BHD340/10`. In Debug, `key_terms: ["bhd340 10"]`. |
| 1:05 | New chat. Send: `I want a refund for my last order` | "Refunds need the real order. The agent pauses and asks which one." | The order picker with five recent orders and "None of these". |
| 1:15 | Click `ORD-000012` (shipped). Wait up to a minute. | "Order facts come only from the order service. The refund rule must come from cited policy. Here the policy evidence is too weak, so the agent hands off instead of deciding." | "Transferred to a human agent — reason: low_evidence". In Debug, the gate score below `threshold: 0.15` and the trace `refund_identify, refund_load, refund_retrieve, handoff`. |
| 1:35 | New chat. Send: `Can I pay with gold bars?` | "No source covers gold bars. The agent does not guess." | "Transferred to a human agent — reason: incomplete_evidence". In Debug, the gate passed, but the coverage check found no cited support. |
| 1:50 | Switch to the README on GitHub. | "Every number here is generated from the eval reports. Zero false accepts on the test set is the main target." | The "Results at a glance" table and its source links. |

## Known gap in this script

The plan asked for a refund that ends in a cited decision.
The current build does not reach one: the refund policy query retrieves weak evidence.
In this verification the gate scored below the threshold for `ORD-000012`, `ORD-000013`, `ORD-000015` and the named fixture `ORD-000001`.
So the 1:15 step shows an honest handoff. Update this step when the refund policy query is fixed.

## Checked outcomes (2026-11-17)

These are single manual runs, not metrics.

- 0:15 Flipkart returns: answered with three citations in some runs (gate 0.84). Other runs handed off at the answer step (`incomplete_evidence`, `invalid_answer`), and one web-page run classified it as `return_exchange`.
- 0:45 BHD340/10: answered "6 heat and speed settings" with one citation (gate 0.85 and 0.73). One run handed off (`incomplete_evidence`); one run hit the classifier fallback.
- 1:05 refund: the picker appeared every time. Picking `ORD-000012` handed off with `low_evidence` (gate 0.138).
- 1:35 gold bars: handed off with `incomplete_evidence` in a new chat (gate passed at 0.23). Sent in the same chat after the refund handoff, it was classified as `talk_to_human` instead.
