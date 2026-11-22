# Eval run comparison

- Run A: `/tmp/atlas-24b/runs-rescored/e2e-test-20261122-b864da21-19944fe3`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `17972d0c996de0223f3e7372424e2181c7dc204453e8d5bee9a08f605e73c53b`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs-rescored/e2e-test-20261122-b864da21-8e795e59`
- Run B Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run B config hash: `b9051ff2cac6e343613d02200da02aa2448056b15706d9fdeab97bdb1143b538`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 120 | 0.859722 | 0.854167 | -0.00555556 | [-0.0416667, +0.0305556] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.108333 | 0.108333 | +0 | [-0.0333333, +0.0333333] | 1 | no significant change |
| full_answer_rate | 30 | 0.866667 | 0.9 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.96875 | 0.960417 | -0.00833333 | [-0.0416667, +0.0166667] | — | no significant change |
| graph_recall_at_5 | 120 | 0.975 | 0.966667 | -0.00833333 | [-0.0416667, +0.0166667] | — | no significant change |
| latency_p50 | 150 | 15.4945 | 14.3209 | -1.17352 | [-2.03177, +0.290663] | — | no significant change |
| latency_p95 | 150 | 23.7207 | 26.3282 | +2.60754 | [-2.9672, +7.53527] | — | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.975 | 0.966667 | -0.00833333 | [-0.0416667, +0.0166667] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.713333 | 0.713333 | +0 | [-0.0266667, +0.0266667] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-621dcf09c082cf6376772077b5a0da3f0fabe420ce1cc947c37ea09c7a5144e9 | True | False | None | order_not_found |
| basic_policy-c3b166e1613c5b20ec9cd4164b4ae9ecd714920beda9094beff12a138c005260 | False | True | agent_step_cap | None |
| colloquial-61497765ed89504bfbdf5493ef0d7170c27beef232e311a667db1cee33d3b03b | True | False | None | incomplete_evidence |
| cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e | False | True | incomplete_evidence | None |
