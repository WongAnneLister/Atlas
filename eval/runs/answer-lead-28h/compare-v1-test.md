# Eval run comparison

- Run A: `/tmp/atlas-r35/lead/runs/e2e-test-20261127-dfe8c4f4-v1-test-before`
- Run A Git SHA: `dfe8c4f4af871d96cc26c96f6879fd9f02ef3f57`
- Run A config hash: `4b565859e7a38ca6bd1ba26c0e40eed836050431e669319fdafdc57a26b4f7c1`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/lead/runs/e2e-test-20261127-dfa1aa54-v1-test-after`
- Run B Git SHA: `dfa1aa548a6e442e67bcec7494249037b47f7b3a`
- Run B config hash: `8643170fa69aaa73336deebe7e11649491eaaaefd65ec2e7429e9a92c9e1bdd4`
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
| answers_with_any_unsupported_claim | 108 | 0.0277778 | 0 | -0.0277778 | [-0.0648148, +0] | 0.25 | no significant change |
| citation_validity | 120 | 0.855556 | 0.859722 | +0.00416667 | [-0.0333333, +0.0416667] | — | no significant change |
| claims_removed_per_answer | 108 | 0.0925926 | 0 | -0.0925926 | [-0.231481, +0] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.133333 | 0.108333 | -0.025 | [-0.0666667, +0.0166667] | 0.4531 | no significant change |
| full_answer_rate | 30 | 0.866667 | 0.833333 | -0.0333333 | [-0.133333, +0.0666667] | 1 | no significant change |
| graph_mrr_at_5 | 120 | 0.977083 | 0.977083 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | — | no significant change |
| low_grounding_handoff_rate | 108 | 0.0185185 | 0 | -0.0185185 | [-0.0462963, +0] | 0.5 | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.983333 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 30 | 0.0333333 | 0 | -0.0333333 | [-0.1, +0] | 1 | no significant change |
| pass_rate | 150 | 0.693333 | 0.713333 | +0.02 | [-0.0133333, +0.0533333] | 0.4531 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-ea4182a11f166da24d06c4b1134c4d40e0ae136ebc8d9f46b660efda1a132416 | False | True | low_grounding | None |
| colloquial-1767c9a35c41e42821677cf1bce7241969cea8e17cdd38e7b479f8cc1b8ee77c | False | True | incomplete_evidence | None |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | False | low_grounding | incomplete_evidence |
| colloquial-936394a4d078a888a3ad1931489aef79fe801dbda3f06f206fba0a0bfd0ff04a | False | True | incomplete_evidence | None |
| colloquial-d49849e80d3226360462d7864cc208e3ad3bad67b726d45fcc888985fa492dfa | False | True | low_grounding | None |
| cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e | True | False | None | incomplete_evidence |
| cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90 | True | False | None | guardrail_blocked |
| cross_doc-ef5f3a1c0c87efa9038a513b697f2fc8acea6534f669bed30adfbc6deee5d67d | False | True | unsupported_part | None |
