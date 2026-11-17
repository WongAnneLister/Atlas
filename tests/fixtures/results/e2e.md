# End-to-end evaluation

- Git SHA: `aaaaaaa1111111111111111111111111111111111`
- Split: test (10 items)
- Date (UTC): 2026-01-03T05:00:00+00:00

## Outcome metrics

| Metric | Value |
|---|---:|
| False accept | 0.00% |
| False reject | 12.50% |
| Accepted | 70.00% (7/10) |
| Recall@5 from graph retrieval | 0.8000 |
| MRR@5 from graph retrieval | 0.7000 |
| Citation validity | 0.6000 |
| Latency P50 full answer | 10.0000s |
| Latency P95 full answer | 20.0000s |

## Cost by intent

| Intent | Items | LLM calls (mean) | Tokens (mean) | Tokens (median) | Cost (mean) | Cost (median) | Share of tokens | Share of cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| product_question | 2 | 2.00 | 3000 | 3000 | $0.00300 | $0.00300 | 75.0% | 75.0% |
| policy_question | 8 | 1.00 | 250 | 250 | $0.00025 | $0.00025 | 25.0% | 25.0% |

## No-answer false accepts
