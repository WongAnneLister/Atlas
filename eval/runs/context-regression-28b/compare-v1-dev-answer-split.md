# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-cbd581b2`
- Run A Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run A config hash: `a27164a21604ca350a7247acdc2913931fd38de8dcac1b9d675c134606b62074`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-dev-20261126-a15a011e-510ab4dd`
- Run B Git SHA: `a15a011eb7690e78c8823289ad867800cf37ec61`
- Run B config hash: `c837f431d5f9fc37b484ef03e01f5e1dd25616b2566ca3365d38903e184f74fe`
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
| answers_with_any_unsupported_claim | 111 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| citation_validity | 120 | 0.865278 | 0.883333 | +0.0180556 | [-0.0138889, +0.0541667] | — | no significant change |
| claims_removed_per_answer | 111 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.116667 | 0.0916667 | -0.025 | [-0.0583333, +0.00833333] | 0.375 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.933333 | +0.0333333 | [-0.0666667, +0.166667] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.979167 | 0.9875 | +0.00833333 | [+0, +0.025] | — | no significant change |
| graph_recall_at_5 | 120 | 0.991667 | 1 | +0.00833333 | [+0, +0.025] | — | no significant change |
| low_grounding_handoff_rate | 111 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.991667 | 1 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.706667 | 0.726667 | +0.02 | [-0.00666667, +0.0533333] | 0.375 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | False | True | invalid_answer | None |
| colloquial-941f661aa51acdb3072362a0f17b4dfb52fa1e03191a9f4149e7da494e7acea9 | False | True | guardrail_blocked | None |
| cross_doc-75b0f8457dab09ccfbd8f9c6112204fd7eb9efa242e6f9cc6b712e79051ad3b8 | False | True | complaint | None |
| cross_doc-d23e5fcf0bd33960e5025dfc9b529f5f25e41281fa94bfb53daa293262028866 | True | False | None | invalid_answer |
| cross_doc-fe7010e21aeeda63e5ce3c8a4ed2bf4a0081fae80eea509e9f4dfbfbe08d8d0c | False | True | guardrail_blocked | None |
