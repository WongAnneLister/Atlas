# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/smoke-test-20261126-07cf8f59-02105599`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `43b5d6a505e7fb143967c59ba749e7200ea4a2609bc950a8f328b924d9f218e0`
- Run A datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/smoke-test-20261126-5bb57ac9-0d953069`
- Run B Git SHA: `5bb57ac9068bc628ecbc5f57cf64ad5acb98a541`
- Run B config hash: `806cd3da1fb20092fcd8d588f7fd77e605957086167af9ee8d97cdbe88cda965`
- Run B datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 70
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answers_with_any_unsupported_claim | 36 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| citation_validity | 40 | 0.866667 | 0.866667 | +0 | [+0, +0] | — | no significant change |
| claims_removed_per_answer | 36 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 40 | 0.1 | 0.1 | +0 | [+0, +0] | 1 | no significant change |
| full_answer_rate | 10 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 70 | 15.1727 | 11.8434 | -3.32925 | [-4.33058, -2.17318] | — | better |
| latency_p95 | 70 | 26.0289 | 25.6282 | -0.400737 | [-3.69439, +8.26288] | — | no significant change |
| low_grounding_handoff_rate | 36 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 70 | 0.514286 | 0.514286 | +0 | [+0, +0] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
