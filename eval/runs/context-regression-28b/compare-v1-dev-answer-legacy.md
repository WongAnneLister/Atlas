# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-cbd581b2`
- Run A Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run A config hash: `a27164a21604ca350a7247acdc2913931fd38de8dcac1b9d675c134606b62074`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-7a6b1a4a`
- Run B Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run B config hash: `3b84554503e91e742022f30de06c889cd729dae68d21c1eeb31b5406f6eb0258`
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
| answers_with_any_unsupported_claim | 112 | 0 | 0.00892857 | +0.00892857 | [+0, +0.0267857] | 1 | no significant change |
| citation_validity | 120 | 0.865278 | 0.873611 | +0.00833333 | [-0.0208333, +0.0416667] | — | no significant change |
| claims_removed_per_answer | 112 | 0 | 0.0178571 | +0.0178571 | [+0, +0.0535714] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.116667 | 0.108333 | -0.00833333 | [-0.0416667, +0.025] | 1 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.9 | +0 | [-0.1, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.979167 | 0.9875 | +0.00833333 | [+0, +0.025] | — | no significant change |
| graph_recall_at_5 | 120 | 0.991667 | 1 | +0.00833333 | [+0, +0.025] | — | no significant change |
| low_grounding_handoff_rate | 112 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.991667 | 1 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0.0333333 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.706667 | 0.713333 | +0.00666667 | [-0.02, +0.0333333] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | False | True | invalid_answer | None |
| colloquial-941f661aa51acdb3072362a0f17b4dfb52fa1e03191a9f4149e7da494e7acea9 | False | True | guardrail_blocked | None |
| colloquial-a8161eb7dd5c7f5a336a0dd6ddb6c766191d499dfb61953e398532ad5ee72710 | True | False | None | guardrail_blocked |
| cross_doc-75b0f8457dab09ccfbd8f9c6112204fd7eb9efa242e6f9cc6b712e79051ad3b8 | False | True | complaint | None |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | True | False | None | unsupported_part |
