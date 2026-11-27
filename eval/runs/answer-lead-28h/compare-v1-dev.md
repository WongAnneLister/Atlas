# Eval run comparison

- Run A: `/tmp/atlas-r35/lead/runs/e2e-dev-20261127-dfe8c4f4-v1-dev-before`
- Run A Git SHA: `dfe8c4f4af871d96cc26c96f6879fd9f02ef3f57`
- Run A config hash: `e8c1cded121f6b7fad2af7bbb48ca2330a92ce95641788087e0f2edd4be4bcae`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/lead/runs/e2e-dev-20261127-dfa1aa54-v1-dev-after`
- Run B Git SHA: `dfa1aa548a6e442e67bcec7494249037b47f7b3a`
- Run B config hash: `6953a437c0c30ec4debcc154cfe6b7622707f93e7ce0afce779bb6e8feef8fd7`
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
| answers_with_any_unsupported_claim | 110 | 0.00909091 | 0.0181818 | +0.00909091 | [-0.0181818, +0.0363636] | 1 | no significant change |
| citation_validity | 120 | 0.865278 | 0.858333 | -0.00694444 | [-0.0555556, +0.0388889] | — | no significant change |
| claims_removed_per_answer | 110 | 0.0181818 | 0.0181818 | +0 | [-0.0454545, +0.0363636] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.116667 | 0.116667 | +0 | [-0.05, +0.05] | 1 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.933333 | +0.0333333 | [-0.0666667, +0.133333] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.9875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 112 | 0 | 0.00892857 | +0.00892857 | [+0, +0.0267857] | 1 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0.0333333 | +0 | [-0.1, +0.1] | 1 | no significant change |
| pass_rate | 150 | 0.706667 | 0.706667 | +0 | [-0.04, +0.04] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-01014845ca4af5576eda43f9d5a457f922ad205ecfd1a68687de7d324aa830ef | True | False | None | low_grounding |
| basic_policy-8897f1f36557b63b2c7aae3f6a78e7ab8b3a23107018b38c29240905253b3bb7 | False | True | dependency_unavailable | None |
| basic_policy-9854ae6245a14795d70e15a2498eccf80e5e4163fe74a4038d894d1b7f52cba4 | True | False | None | dependency_unavailable |
| colloquial-01d716f80e3fa7ea307976ac2087d1e59f2173c30a39ac0819e92fcebcf5b84e | True | False | None | incomplete_evidence |
| colloquial-073f5c61bb95c1611b08a12b0d953c4bb58faa958e43e019401a7aaeb5f96ebf | False | True | invalid_answer | None |
| colloquial-720495fc694927f004912e6951a17b17f5ce17c8dbd5eb48797a2a17f582a4cc | False | True | guardrail_blocked | None |
| colloquial-a8161eb7dd5c7f5a336a0dd6ddb6c766191d499dfb61953e398532ad5ee72710 | True | False | None | guardrail_blocked |
| cross_doc-03827aa25f082b6fe941efd4d3fa5de63f6395332caa1bcf6083cafae8f385e5 | True | False | None | unsupported_part |
| cross_doc-7feb3944b2f177b20922680752027fd5451073b6eff48f46b83fe4eb9d11ee6e | False | True | invalid_answer | None |
| cross_doc-eff062b04a88dd72ced0efe0f902f081df923a0f9eb654c443fb1a1a4c8b72b2 | False | True | unsupported_part | None |
