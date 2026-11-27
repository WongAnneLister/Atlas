# Eval run comparison

- Run A: `/tmp/atlas-r35/budget/item-runs/e2e-test-20261127-ca51a9e1-off1`
- Run A Git SHA: `ca51a9e1da728d4d03fad35ea05d65856b3f8378`
- Run A config hash: `5f7224e1e8847bb45d94fddbf36b67e805b1a85adde64b10c30ff1427c779a6a`
- Run A datasets: `{'unregistered': DatasetVersion(version=None, sha256='1efb1c1149a4b90f728b08becda16747140566df4a17e84e132de3b13490ed73')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/budget/item-runs/e2e-test-20261127-ca51a9e1-on1`
- Run B Git SHA: `ca51a9e1da728d4d03fad35ea05d65856b3f8378`
- Run B config hash: `5b340b9f8eaf99a917daaffe73299976604ea269cc1cd318a9ea4c209660f530`
- Run B datasets: `{'unregistered': DatasetVersion(version=None, sha256='1efb1c1149a4b90f728b08becda16747140566df4a17e84e132de3b13490ed73')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 1
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answers_with_any_unsupported_claim | 1 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| citation_validity | 1 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| claims_removed_per_answer | 1 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| false_reject | 1 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| full_answer_rate | 1 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 1 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 1 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 1 | 49.5709 | 48.3903 | -1.1806 | [-1.1806, -1.1806] | — | better |
| latency_p95 | 1 | 49.5709 | 48.3903 | -1.1806 | [-1.1806, -1.1806] | — | better |
| low_grounding_handoff_rate | 1 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 1 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 1 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 1 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
