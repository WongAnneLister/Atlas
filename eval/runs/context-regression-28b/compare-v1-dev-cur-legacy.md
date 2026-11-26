# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/e2e-dev-20261126-7f0973a1-2c19b373`
- Run A Git SHA: `7f0973a160e8dfb956837449deecb7fa156c59bf`
- Run A config hash: `39897910d2aae53adce131a5e00e62424605a34af01e9e8ba7c61e04721f0f59`
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
| answers_with_any_unsupported_claim | 111 | 0 | 0.00900901 | +0.00900901 | [+0, +0.027027] | 1 | no significant change |
| citation_validity | 120 | 0.893056 | 0.873611 | -0.0194444 | [-0.0652778, +0.0236458] | — | no significant change |
| claims_removed_per_answer | 111 | 0 | 0.018018 | +0.018018 | [+0, +0.0540541] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0916667 | 0.108333 | +0.0166667 | [-0.0333333, +0.0666667] | 0.7266 | no significant change |
| full_answer_rate | 30 | 1 | 0.9 | -0.1 | [-0.200833, +0] | 0.25 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.9875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 112 | 0.00892857 | 0 | -0.00892857 | [-0.0267857, +0] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0.0333333 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.726667 | 0.713333 | -0.0133333 | [-0.0533333, +0.0266667] | 0.7266 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-9d057f7bfe7dd039a19bfed7d7ceb305feb82c59d9e0ac60ade2a52373a561f8 | False | True | guardrail_blocked | None |
| colloquial-1fc19a21aefd8a21202033e65b5444dd0a32ae175f009318e433597f422d2d2a | False | False | low_grounding | guardrail_blocked |
| colloquial-720495fc694927f004912e6951a17b17f5ce17c8dbd5eb48797a2a17f582a4cc | True | False | None | guardrail_blocked |
| colloquial-90bb934c3dc0c710cd6c17c9de91cfbb493497ac0056d4e5902c2ad8c05b64fc | False | True | incomplete_evidence | None |
| colloquial-a8161eb7dd5c7f5a336a0dd6ddb6c766191d499dfb61953e398532ad5ee72710 | True | False | None | guardrail_blocked |
| colloquial-b8db47c5e87bb42200ca8357093c9470dbfd6e76316eb1940e981a65ffbd0db5 | False | True | incomplete_evidence | None |
| cross_doc-7feb3944b2f177b20922680752027fd5451073b6eff48f46b83fe4eb9d11ee6e | True | False | None | invalid_answer |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | True | False | None | unsupported_part |
| cross_doc-fe7010e21aeeda63e5ce3c8a4ed2bf4a0081fae80eea509e9f4dfbfbe08d8d0c | True | False | None | guardrail_blocked |
