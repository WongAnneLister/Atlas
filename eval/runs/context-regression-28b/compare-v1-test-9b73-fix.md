# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-test-20261126-9b7350e6-781fefb3`
- Run A Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run A config hash: `71f2e18ed4fea8b6c99f41aa4e554c9d867d3baed8df0e80fa6ed8f84a060a7f`
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
| answers_with_any_unsupported_claim | 101 | 0.029703 | 0.019802 | -0.00990099 | [-0.029703, +0] | 1 | no significant change |
| citation_validity | 120 | 0.776389 | 0.859722 | +0.0833333 | [+0.0333333, +0.1375] | — | better |
| claims_removed_per_answer | 101 | 0.0792079 | 0.0693069 | -0.00990099 | [-0.029703, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.2 | 0.125 | -0.075 | [-0.125, -0.025] | 0.01172 | better |
| full_answer_rate | 30 | 0.8 | 0.833333 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.977083 | 0.977083 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 102 | 0.0294118 | 0.00980392 | -0.0196078 | [-0.0490196, +0] | 0.5 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.64 | 0.7 | +0.06 | [+0.02, +0.1] | 0.01172 | better |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-6ca5448307637e6f8c16ad7b8b579a74cbfa0644b7fd8620a357840bd0d9fad0 | False | True | incomplete_evidence | None |
| basic_policy-918565ca322457eaf9c674318535a27d62213cd28395ac791e37299d83ffe068 | False | True | low_grounding | None |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | True | incomplete_evidence | None |
| colloquial-446217d7521df6af5c067f05ec9fed48b090d941c68eb84b58e0469965b5687c | False | True | incomplete_evidence | None |
| colloquial-61497765ed89504bfbdf5493ef0d7170c27beef232e311a667db1cee33d3b03b | False | True | incomplete_evidence | None |
| colloquial-aa1801d17e55b415b7a305f67cfd7061dcb417bd988a9b9c499d779261394f0b | False | True | low_grounding | None |
| colloquial-be04851050d42e218fc4a91af51ac75ac54d17334f3c8d76b8722f839e131e65 | False | True | incomplete_evidence | None |
| colloquial-f03d337b2bb35d6d9623242cd57883279d75698588ffd78c71d9beda8be0b9a5 | True | False | None | invalid_answer |
| colloquial-f80188088ec68f15d2073230c602cad90043c8c15c27264a6913971bd769d11d | False | True | guardrail_blocked | None |
| cross_doc-85c29a37067aba7ba527a3867287823b7465b23d99df1e612923a0cab921ee87 | False | True | context_overflow | None |
| model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3 | False | True | invalid_answer | None |
