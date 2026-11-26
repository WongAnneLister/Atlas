# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/e2e-test-20261122-07cf8f59-7203ff90`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `70127a8657277c9adabd677bcf14396c9de2ca6eae656906b744292bd28fd4df`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-test-20261126-9b7350e6-781fefb3`
- Run B Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run B config hash: `71f2e18ed4fea8b6c99f41aa4e554c9d867d3baed8df0e80fa6ed8f84a060a7f`
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
| answers_with_any_unsupported_claim | 100 | 0.01 | 0.03 | +0.02 | [+0, +0.05] | 0.5 | no significant change |
| citation_validity | 120 | 0.847222 | 0.776389 | -0.0708333 | [-0.120833, -0.0208333] | — | worse |
| claims_removed_per_answer | 100 | 0.01 | 0.08 | +0.07 | [+0, +0.2] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.133333 | 0.2 | +0.0666667 | [+0.0166667, +0.116667] | 0.02148 | worse |
| full_answer_rate | 30 | 0.833333 | 0.8 | -0.0333333 | [-0.1, +0] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.96875 | 0.977083 | +0.00833333 | [+0, +0.025] | — | no significant change |
| graph_recall_at_5 | 120 | 0.975 | 0.983333 | +0.00833333 | [+0, +0.025] | — | no significant change |
| low_grounding_handoff_rate | 101 | 0 | 0.029703 | +0.029703 | [+0, +0.0693069] | 0.25 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.975 | 0.983333 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.693333 | 0.64 | -0.0533333 | [-0.0933333, -0.0133333] | 0.02148 | worse |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-6ca5448307637e6f8c16ad7b8b579a74cbfa0644b7fd8620a357840bd0d9fad0 | True | False | None | incomplete_evidence |
| basic_policy-918565ca322457eaf9c674318535a27d62213cd28395ac791e37299d83ffe068 | True | False | None | low_grounding |
| basic_policy-ea4182a11f166da24d06c4b1134c4d40e0ae136ebc8d9f46b660efda1a132416 | True | False | None | low_grounding |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | False | low_grounding | incomplete_evidence |
| colloquial-446217d7521df6af5c067f05ec9fed48b090d941c68eb84b58e0469965b5687c | True | False | None | incomplete_evidence |
| colloquial-936394a4d078a888a3ad1931489aef79fe801dbda3f06f206fba0a0bfd0ff04a | False | True | incomplete_evidence | None |
| colloquial-aa1801d17e55b415b7a305f67cfd7061dcb417bd988a9b9c499d779261394f0b | True | False | None | low_grounding |
| colloquial-be04851050d42e218fc4a91af51ac75ac54d17334f3c8d76b8722f839e131e65 | True | False | None | incomplete_evidence |
| colloquial-f80188088ec68f15d2073230c602cad90043c8c15c27264a6913971bd769d11d | True | False | None | guardrail_blocked |
| cross_doc-85c29a37067aba7ba527a3867287823b7465b23d99df1e612923a0cab921ee87 | True | False | None | context_overflow |
| model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3 | True | False | None | invalid_answer |
