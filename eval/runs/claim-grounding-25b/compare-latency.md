# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/smoke-test-20261122-07cf8f59-e6384686`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `afd4e3b62baac0d24cd38b5ec2b19c8b440427e45119ff59b8bae05d8b8f6d9d`
- Run A datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-25b/runs/smoke-test-20261122-07cf8f59-309f9b4a`
- Run B Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run B config hash: `ffd7fc9bcdc7a701c69374e052dee234e72da5f88d5086cd6ded31cd666e7e53`
- Run B datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 70
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 40 | 0.875 | 0.875 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 40 | 0.1 | 0.1 | +0 | [+0, +0] | 1 | no significant change |
| full_answer_rate | 10 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 70 | 9.09006 | 9.98041 | +0.890343 | [+0.380354, +1.45732] | — | worse |
| latency_p95 | 70 | 19.1183 | 22.5288 | +3.41049 | [+1.82846, +4.65916] | — | worse |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 70 | 0.514286 | 0.514286 | +0 | [+0, +0] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
