# Eval run comparison

- Run A: `eval/runs/smoke-test-20261121-c80a8668-ed86add9`
- Run A Git SHA: `c80a86680e8de321580d71656fd2929a6385d127`
- Run A config hash: `4cd25a2c4f502373923125c0bb5521e73f934afa47484840a26e5e87a4b10eaa`
- Run A datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `eval/runs/smoke-test-20261121-b7d761af-dc9d2d85`
- Run B Git SHA: `b7d761af3a9ac4887ce93526f75cf4b0768a4714`
- Run B config hash: `9fcc2aaa86717044a9f875fafbe4bccc054602b6e5c021e336ff48f28e803661`
- Run B datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 70
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 40 | 0.85 | 0.841667 | -0.00833333 | [-0.075, +0.05] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 40 | 0.125 | 0.125 | +0 | [-0.075, +0.075] | 1 | no significant change |
| graph_mrr_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 70 | 25.9259 | 25.047 | -0.878952 | [-1.86414, -0.293373] | — | better |
| latency_p95 | 70 | 32.1779 | 31.2293 | -0.94865 | [-17.2225, +4.07296] | — | no significant change |
| pass_rate | 70 | 0.5 | 0.5 | +0 | [-0.0428571, +0.0428571] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-f6f6dae584fc8096bb9d7d4a65f46c055913e248826da762d31d5f76f274cdde | True | False | None | incomplete_evidence |
| cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90 | False | True | dependency_unavailable | None |
| no_answer-fadce2c90af8a3c81d0377ca8ad3ad0cba403725b5bb5a8c8ddddfd6853f072e | False | False | low_evidence | None |
