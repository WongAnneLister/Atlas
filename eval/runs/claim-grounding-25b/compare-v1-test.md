# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/e2e-test-20261122-07cf8f59-2691f820`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `eeaaf5bad895b7227e5cf22c8359a68db1e030e66a9dce8fcbfb3558d2819b37`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-25b/runs/e2e-test-20261122-07cf8f59-7203ff90`
- Run B Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run B config hash: `70127a8657277c9adabd677bcf14396c9de2ca6eae656906b744292bd28fd4df`
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
| citation_validity | 120 | 0.875 | 0.847222 | -0.0277778 | [-0.0583333, -0.00277778] | — | worse |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.1 | 0.133333 | +0.0333333 | [+0.00833333, +0.0666667] | 0.125 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.833333 | -0.0666667 | [-0.166667, +0] | 0.5 | no significant change |
| graph_mrr_at_5 | 120 | 0.96875 | 0.96875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.975 | 0.975 | +0 | [+0, +0] | — | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0.0333333 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.72 | 0.693333 | -0.0266667 | [-0.0533333, -0.00666667] | 0.125 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | True | False | None | low_grounding |
| colloquial-61497765ed89504bfbdf5493ef0d7170c27beef232e311a667db1cee33d3b03b | True | False | None | incomplete_evidence |
| cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e | True | False | None | incomplete_evidence |
| cross_doc-ef5f3a1c0c87efa9038a513b697f2fc8acea6534f669bed30adfbc6deee5d67d | True | False | None | unsupported_part |
