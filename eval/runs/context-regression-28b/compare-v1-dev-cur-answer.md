# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-2c19b373`
- Run A Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run A config hash: `39897910d2aae53adce131a5e00e62424605a34af01e9e8ba7c61e04721f0f59`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-cbd581b2`
- Run B Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run B config hash: `a27164a21604ca350a7247acdc2913931fd38de8dcac1b9d675c134606b62074`
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
| answers_with_any_unsupported_claim | 109 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| citation_validity | 120 | 0.893056 | 0.865278 | -0.0277778 | [-0.0791667, +0.0236111] | — | no significant change |
| claims_removed_per_answer | 109 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0916667 | 0.116667 | +0.025 | [-0.025, +0.075] | 0.5078 | no significant change |
| full_answer_rate | 30 | 1 | 0.9 | -0.1 | [-0.233333, +0] | 0.25 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.979167 | -0.00833333 | [-0.025, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 1 | 0.991667 | -0.00833333 | [-0.025, +0] | — | no significant change |
| low_grounding_handoff_rate | 110 | 0.00909091 | 0 | -0.00909091 | [-0.0272727, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 0.991667 | -0.00833333 | [-0.025, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.726667 | 0.706667 | -0.02 | [-0.06, +0.02] | 0.5078 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-9d057f7bfe7dd039a19bfed7d7ceb305feb82c59d9e0ac60ade2a52373a561f8 | False | True | guardrail_blocked | None |
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | True | False | None | invalid_answer |
| colloquial-1fc19a21aefd8a21202033e65b5444dd0a32ae175f009318e433597f422d2d2a | False | False | low_grounding | guardrail_blocked |
| colloquial-720495fc694927f004912e6951a17b17f5ce17c8dbd5eb48797a2a17f582a4cc | True | False | None | guardrail_blocked |
| colloquial-90bb934c3dc0c710cd6c17c9de91cfbb493497ac0056d4e5902c2ad8c05b64fc | False | True | incomplete_evidence | None |
| colloquial-941f661aa51acdb3072362a0f17b4dfb52fa1e03191a9f4149e7da494e7acea9 | True | False | None | guardrail_blocked |
| colloquial-b8db47c5e87bb42200ca8357093c9470dbfd6e76316eb1940e981a65ffbd0db5 | False | True | incomplete_evidence | None |
| cross_doc-75b0f8457dab09ccfbd8f9c6112204fd7eb9efa242e6f9cc6b712e79051ad3b8 | True | False | None | complaint |
| cross_doc-7feb3944b2f177b20922680752027fd5451073b6eff48f46b83fe4eb9d11ee6e | True | False | None | invalid_answer |
| cross_doc-fe7010e21aeeda63e5ce3c8a4ed2bf4a0081fae80eea509e9f4dfbfbe08d8d0c | True | False | None | guardrail_blocked |
