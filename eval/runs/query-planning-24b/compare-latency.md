# Eval run comparison

- Run A: `/tmp/atlas-24b/runs-rescored/smoke-test-20261122-b864da21-f018cc45`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `640e4ff272e20ce775f7653b792b82e98cdce8d6ef95f4ac1b9f9aa866bf85c1`
- Run A datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs-rescored/smoke-test-20261122-788ab308-8a239fce`
- Run B Git SHA: `788ab3087462019df52f7d5b033e9bf71ead99d3`
- Run B config hash: `685145093d902001fd07f2f073dcc05df3c76236fa8ea2d8c92b1d43e6fc538b`
- Run B datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 70
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 40 | 0.866667 | 0.866667 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 40 | 0.1 | 0.1 | +0 | [+0, +0] | 1 | no significant change |
| full_answer_rate | 10 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 70 | 10.631 | 9.70848 | -0.922567 | [-1.3503, -0.274921] | — | better |
| latency_p95 | 70 | 14.2614 | 21.4438 | +7.18235 | [+2.54665, +9.16091] | — | worse |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 70 | 0.514286 | 0.514286 | +0 | [+0, +0] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
