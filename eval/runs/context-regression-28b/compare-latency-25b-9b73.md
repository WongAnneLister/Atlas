# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/smoke-test-20261122-07cf8f59-309f9b4a`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `ffd7fc9bcdc7a701c69374e052dee234e72da5f88d5086cd6ded31cd666e7e53`
- Run A datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/smoke-test-20261126-9b7350e6-7bc8f588`
- Run B Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run B config hash: `b325476a9edbc8028a88471b7790fcb4fdf64495ff83496e67bcdbeb8cda80f4`
- Run B datasets: `{'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 70
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answers_with_any_unsupported_claim | 34 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| citation_validity | 40 | 0.875 | 0.829167 | -0.0458333 | [-0.125, +0.0166667] | — | no significant change |
| claims_removed_per_answer | 34 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 40 | 0.1 | 0.15 | +0.05 | [+0, +0.125] | 0.5 | no significant change |
| full_answer_rate | 10 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| graph_mrr_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| latency_p50 | 70 | 9.98041 | 14.6619 | +4.68147 | [+2.30935, +5.27952] | — | worse |
| latency_p95 | 70 | 22.5288 | 24.3572 | +1.82839 | [-0.0593445, +12.716] | — | no significant change |
| low_grounding_handoff_rate | 34 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 70 | 0.514286 | 0.485714 | -0.0285714 | [-0.0714286, +0] | 0.5 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-446217d7521df6af5c067f05ec9fed48b090d941c68eb84b58e0469965b5687c | True | False | None | incomplete_evidence |
| model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3 | True | False | None | invalid_answer |
