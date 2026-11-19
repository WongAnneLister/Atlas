# Eval run comparison

- Run A: `eval/runs/e2e-test-c15.jsonl`
- Run A Git SHA: `266c1e85a85208a3c5592a5b5ed1f995a8c6f9ea`
- Run A config hash: `cd882d7fc98e06610ddee32fce7c958890b72ca189c42fcf30efe50c00ba8f7b`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `eval/runs/e2e-test-20261117-266c1e85-legacy`
- Run B Git SHA: `266c1e85a85208a3c5592a5b5ed1f995a8c6f9ea`
- Run B config hash: `cd882d7fc98e06610ddee32fce7c958890b72ca189c42fcf30efe50c00ba8f7b`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 120 | 0.710417 | 0.710417 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.216667 | 0.216667 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.908333 | 0.908333 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.908333 | 0.908333 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 150 | 16.1277 | 16.1277 | +0 | [+0, +0] | — | no significant change |
| latency_p95 | 150 | 28.1733 | 28.1733 | +0 | [+0, +0] | — | no significant change |
| pass_rate | 150 | 0.626667 | 0.626667 | +0 | [+0, +0] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
