# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-test-20261126-a15a011e-07795716`
- Run A Git SHA: `a15a011eb7690e78c8823289ad867800cf37ec61`
- Run A config hash: `4dc1fdea638f1d914889c8c846a2da3986aaff3f014dfe5cb6eb53067c7c0fb6`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/reg1128/runs/e2e-test-20261128-ab6c1e41-5569cbf6`
- Run B Git SHA: `ab6c1e4156c0ee5ae65fa8db5a2c2ff1a49681ec`
- Run B config hash: `0ac6025e7e48f009d0e686b8f748c2460d9148a01164c444de92a9aafb504be8`
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
| answers_with_any_unsupported_claim | 109 | 0.0183486 | 0 | -0.0183486 | [-0.0458716, +0] | 0.5 | no significant change |
| citation_validity | 120 | 0.8625 | 0.884722 | +0.0222222 | [-0.0152778, +0.0638889] | — | no significant change |
| claims_removed_per_answer | 109 | 0.0642202 | 0 | -0.0642202 | [-0.183716, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.125 | 0.0916667 | -0.0333333 | [-0.075, +0] | 0.2188 | no significant change |
| full_answer_rate | 30 | 0.833333 | 0.866667 | +0.0333333 | [-0.0666667, +0.133333] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.977083 | 0.977083 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 109 | 0.00917431 | 0 | -0.00917431 | [-0.0275229, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0 | -0.0333333 | [-0.1, +0] | 1 | no significant change |
| pass_rate | 150 | 0.7 | 0.726667 | +0.0266667 | [+0, +0.06] | 0.2188 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-1767c9a35c41e42821677cf1bce7241969cea8e17cdd38e7b479f8cc1b8ee77c | False | True | incomplete_evidence | None |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | True | low_grounding | None |
| cross_doc-71522fdb53607968881c1f46300f191407cbb57faf107c677f3b1f2a8e1215ef | False | True | guardrail_blocked | None |
| cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90 | True | False | None | guardrail_blocked |
| cross_doc-ef5f3a1c0c87efa9038a513b697f2fc8acea6534f669bed30adfbc6deee5d67d | False | True | unsupported_part | None |
| model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3 | False | True | invalid_answer | None |
