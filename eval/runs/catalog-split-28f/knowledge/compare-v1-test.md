# Eval run comparison

- Run A: `<scratch>/cache/v1-test-before.jsonl`
- Run A Git SHA: `9a9ac2d20bcf825dc247e7c7f8f792d01f0cc174`
- Run A config hash: `af22edf5f8b4630e9263a0b90dbdbc889f0e1ed4fa3b907bbf843eaa9f2d330c`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `<scratch>/cache/v1-test-after.jsonl`
- Run B Git SHA: `00114f5e3b95e48b54acfb1517bcd05d61785709`
- Run B config hash: `d7ad12a417f847cc145cea65e07ff45b1704267d7f52f02d1f2e44633acc98c9`
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
| answers_with_any_unsupported_claim | 110 | 0.0181818 | 0.0272727 | +0.00909091 | [+0, +0.0272727] | 1 | no significant change |
| citation_validity | 120 | 0.876389 | 0.876389 | +0 | [-0.0333333, +0.0333333] | — | no significant change |
| claims_removed_per_answer | 110 | 0.0636364 | 0.118182 | +0.0545455 | [+0, +0.163636] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.108333 | 0.108333 | +0 | [-0.0333333, +0.0333333] | 1 | no significant change |
| full_answer_rate | 30 | 0.833333 | 0.866667 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.977083 | 0.985417 | +0.00833333 | [+0, +0.025] | — | no significant change |
| graph_recall_at_5 | 120 | 0.983333 | 0.991667 | +0.00833333 | [+0, +0.025] | — | no significant change |
| low_grounding_handoff_rate | 110 | 0.00909091 | 0.0181818 | +0.00909091 | [+0, +0.0272727] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.991667 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.713333 | 0.713333 | +0 | [-0.0266667, +0.0266667] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-621dcf09c082cf6376772077b5a0da3f0fabe420ce1cc947c37ea09c7a5144e9 | False | True | order_not_found | None |
| colloquial-1767c9a35c41e42821677cf1bce7241969cea8e17cdd38e7b479f8cc1b8ee77c | True | False | None | incomplete_evidence |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | True | False | None | low_grounding |
| cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e | False | True | incomplete_evidence | None |
