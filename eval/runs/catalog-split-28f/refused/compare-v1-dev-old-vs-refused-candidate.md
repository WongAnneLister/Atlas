# Eval run comparison

- Run A: `<scratch>/cache/v1-dev-before.jsonl`
- Run A Git SHA: `9a9ac2d20bcf825dc247e7c7f8f792d01f0cc174`
- Run A config hash: `b4cf42bf5932192d134d9c488670ae74fdf103cc5442f69d647e7e300b84d1e8`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `<scratch>/cache/v1-dev-cand.jsonl`
- Run B Git SHA: `9a9ac2d20bcf825dc247e7c7f8f792d01f0cc174`
- Run B config hash: `9d10b494e6dfbc0e15a7c74b9c3e1dcda3748e5374c4aa3ddf93b74b41c197ad`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: dev
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0
- Latency not compared: a run collected items concurrently (workers 3, 3).

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answers_with_any_unsupported_claim | 113 | 0.00884956 | 0.00884956 | +0 | [-0.0265487, +0.0265487] | 1 | no significant change |
| citation_validity | 120 | 0.886111 | 0.888889 | +0.00277778 | [-0.00972222, +0.0166667] | — | no significant change |
| claims_removed_per_answer | 113 | 0.0353982 | 0.0176991 | -0.0176991 | [-0.106195, +0.0530973] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0916667 | 0.108333 | +0.0166667 | [-0.0166667, +0.05] | 0.625 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.9 | +0 | [-0.1, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.944444 | -0.0430556 | [-0.0694792, -0.0194444] | — | worse |
| graph_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 113 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [-0.1, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.726667 | 0.713333 | -0.0133333 | [-0.04, +0.00683333] | 0.625 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | True | False | None | invalid_answer |
| colloquial-0766d2b528396da12df38f68d3b8da2d31fbab38df764fbad717a741b4caaf90 | True | False | None | unsupported_part |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | True | False | None | unsupported_part |
| cross_doc-fe9a123f5ddc0f234a2534c5a719b565c478ab411207864b8e103ce8db03c9e8 | False | True | unsupported_part | None |
