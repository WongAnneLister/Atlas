# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/e2e-dev-20261122-07cf8f59-14184b67`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `f17351d809ea8cbe7cd49f5974b46f2924b91cc096f9cbf4d1118faa28ceb7ed`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/e2e-dev-20261126-9b7350e6-3755e1ae`
- Run B Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run B config hash: `5aae75cf2d65984d8cf99e7852cd1bd18dd7e14f6ec014567c65ce6c20966205`
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
| answers_with_any_unsupported_claim | 111 | 0.00900901 | 0.00900901 | +0 | [-0.027027, +0.027027] | 1 | no significant change |
| citation_validity | 120 | 0.894444 | 0.872222 | -0.0222222 | [-0.0638889, +0.0180903] | — | no significant change |
| claims_removed_per_answer | 111 | 0.018018 | 0.00900901 | -0.00900901 | [-0.0540541, +0.027027] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0833333 | 0.1 | +0.0166667 | [-0.025, +0.0666667] | 0.7266 | no significant change |
| full_answer_rate | 30 | 0.966667 | 1 | +0.0333333 | [+0, +0.1] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.9875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 112 | 0 | 0.00892857 | +0.00892857 | [+0, +0.0267857] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0 | -0.0333333 | [-0.1, +0] | 1 | no significant change |
| pass_rate | 150 | 0.733333 | 0.72 | -0.0133333 | [-0.0466667, +0.0266667] | 0.7266 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-9d057f7bfe7dd039a19bfed7d7ceb305feb82c59d9e0ac60ade2a52373a561f8 | True | False | None | guardrail_blocked |
| colloquial-01d716f80e3fa7ea307976ac2087d1e59f2173c30a39ac0819e92fcebcf5b84e | True | False | None | incomplete_evidence |
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | True | False | None | invalid_answer |
| colloquial-0766d2b528396da12df38f68d3b8da2d31fbab38df764fbad717a741b4caaf90 | True | False | None | unsupported_part |
| colloquial-3ad400dfea781b56b28dc0caf37a444d5f456dc50e5152489c1c79a4ed3c74c7 | False | False | guardrail_blocked | low_grounding |
| colloquial-720495fc694927f004912e6951a17b17f5ce17c8dbd5eb48797a2a17f582a4cc | False | True | guardrail_blocked | None |
| colloquial-90bb934c3dc0c710cd6c17c9de91cfbb493497ac0056d4e5902c2ad8c05b64fc | True | False | None | incomplete_evidence |
| colloquial-941f661aa51acdb3072362a0f17b4dfb52fa1e03191a9f4149e7da494e7acea9 | False | True | guardrail_blocked | None |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | False | True | unsupported_part | None |
