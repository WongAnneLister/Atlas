# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/e2e-test-20261122-07cf8f59-7203ff90`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `70127a8657277c9adabd677bcf14396c9de2ca6eae656906b744292bd28fd4df`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-test-20261126-7f0973a1-91a09bb2`
- Run B Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run B config hash: `fec9bcba09346aedcc86ddcfabac1cf70589a7512fdde7ebe60a895437a00b71`
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
| answers_with_any_unsupported_claim | 106 | 0.0188679 | 0.0188679 | +0 | [-0.0283019, +0.0283019] | 1 | no significant change |
| citation_validity | 120 | 0.847222 | 0.859722 | +0.0125 | [-0.025, +0.05] | — | no significant change |
| claims_removed_per_answer | 106 | 0.0660377 | 0.0660377 | +0 | [-0.169811, +0.169811] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.133333 | 0.125 | -0.00833333 | [-0.0416667, +0.025] | 1 | no significant change |
| full_answer_rate | 30 | 0.833333 | 0.833333 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.96875 | 0.977083 | +0.00833333 | [+0, +0.025] | — | no significant change |
| graph_recall_at_5 | 120 | 0.975 | 0.983333 | +0.00833333 | [+0, +0.025] | — | no significant change |
| low_grounding_handoff_rate | 106 | 0.00943396 | 0.00943396 | +0 | [-0.0283019, +0.0283019] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.975 | 0.983333 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.693333 | 0.7 | +0.00666667 | [-0.02, +0.0333333] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-ea4182a11f166da24d06c4b1134c4d40e0ae136ebc8d9f46b660efda1a132416 | True | False | None | low_grounding |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | True | low_grounding | None |
| colloquial-61497765ed89504bfbdf5493ef0d7170c27beef232e311a667db1cee33d3b03b | False | True | incomplete_evidence | None |
| colloquial-936394a4d078a888a3ad1931489aef79fe801dbda3f06f206fba0a0bfd0ff04a | False | True | incomplete_evidence | None |
| colloquial-f03d337b2bb35d6d9623242cd57883279d75698588ffd78c71d9beda8be0b9a5 | True | False | None | invalid_answer |
