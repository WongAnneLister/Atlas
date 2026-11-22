# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/e2e-dev-20261122-07cf8f59-bfff1bc3`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `7b24a4be748f23fe45059f56dcf254e14d024f280385b30aff8ca4471bb114f5`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-25b/runs/e2e-dev-20261122-07cf8f59-14184b67`
- Run B Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run B config hash: `f17351d809ea8cbe7cd49f5974b46f2924b91cc096f9cbf4d1118faa28ceb7ed`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: dev
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0
- Latency not compared: a run collected items concurrently (workers 3, 3).

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 120 | 0.879167 | 0.894444 | +0.0152778 | [-0.00416667, +0.0402778] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0916667 | 0.0833333 | -0.00833333 | [-0.0333333, +0.0166667] | 1 | no significant change |
| full_answer_rate | 30 | 0.933333 | 0.966667 | +0.0333333 | [-0.0666667, +0.133333] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.9875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0.0333333 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.726667 | 0.733333 | +0.00666667 | [-0.0133333, +0.0333333] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| cross_doc-7feb3944b2f177b20922680752027fd5451073b6eff48f46b83fe4eb9d11ee6e | False | True | invalid_answer | None |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | True | False | None | unsupported_part |
| cross_doc-fe7010e21aeeda63e5ce3c8a4ed2bf4a0081fae80eea509e9f4dfbfbe08d8d0c | False | True | guardrail_blocked | None |
