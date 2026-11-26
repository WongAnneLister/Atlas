# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-test-20261126-7f0973a1-91a09bb2`
- Run A Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run A config hash: `fec9bcba09346aedcc86ddcfabac1cf70589a7512fdde7ebe60a895437a00b71`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-test-20261126-a15a011e-07795716`
- Run B Git SHA: `a15a011eb7690e78c8823289ad867800cf37ec61`
- Run B config hash: `4dc1fdea638f1d914889c8c846a2da3986aaff3f014dfe5cb6eb53067c7c0fb6`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0
- Latency not compared: a run collected items concurrently (workers 3, 3).

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answers_with_any_unsupported_claim | 108 | 0.0185185 | 0.0185185 | +0 | [-0.0277778, +0.0277778] | 1 | no significant change |
| citation_validity | 120 | 0.859722 | 0.8625 | +0.00277778 | [-0.0333333, +0.0361111] | — | no significant change |
| claims_removed_per_answer | 108 | 0.0648148 | 0.0648148 | +0 | [-0.166667, +0.166667] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.125 | 0.125 | +0 | [-0.0333333, +0.0333333] | 1 | no significant change |
| full_answer_rate | 30 | 0.833333 | 0.833333 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.977083 | 0.977083 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 108 | 0.00925926 | 0.00925926 | +0 | [-0.0277778, +0.0277778] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.7 | 0.7 | +0 | [-0.0266667, +0.0266667] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-ea4182a11f166da24d06c4b1134c4d40e0ae136ebc8d9f46b660efda1a132416 | False | True | low_grounding | None |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | True | False | None | low_grounding |
| colloquial-f03d337b2bb35d6d9623242cd57883279d75698588ffd78c71d9beda8be0b9a5 | False | True | invalid_answer | None |
| model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3 | True | False | None | invalid_answer |
