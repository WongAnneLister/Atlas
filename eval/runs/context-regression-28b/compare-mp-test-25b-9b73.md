# Eval run comparison

- Run A: `/tmp/atlas-25b/runs/multipart-test-20261122-07cf8f59-5995ba37f1a3437faa7f60a57a730a73`
- Run A Git SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Run A config hash: `ffd7fc9bcdc7a701c69374e052dee234e72da5f88d5086cd6ded31cd666e7e53`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/multipart-test-20261126-9b7350e6-7952421bee4b4ecaaf56cf66891b2257`
- Run B Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run B config hash: `06b38d52beeeb654770d5098df42cd0ad24b07f605653294706e2e0f0008d438`
- Run B datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 50
- Only in A: 0
- Only in B: 0
- Latency not compared: a run collected items concurrently (workers 3, 3).

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answered_part_correct | 20 | 0.65 | 0.6 | -0.05 | [-0.15, +0] | 1 | no significant change |
| answers_with_any_unsupported_claim | 30 | 0.0333333 | 0 | -0.0333333 | [-0.1, +0] | 1 | no significant change |
| claims_removed_per_answer | 30 | 0.0333333 | 0 | -0.0333333 | [-0.1, +0] | — | no significant change |
| full_answer_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| low_grounding_handoff_rate | 32 | 0 | 0.03125 | +0.03125 | [+0, +0.09375] | 1 | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0.26 | 0.24 | -0.02 | [-0.06, +0] | 1 | no significant change |
| pass_rate | 50 | 0.36 | 0.36 | +0 | [-0.06, +0.06] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/answers_with_any_unsupported_claim | 18 | 0.0555556 | 0 | -0.0555556 | [-0.166667, +0] | 1 | no significant change |
| answerable_pair/claims_removed_per_answer | 18 | 0.0555556 | 0 | -0.0555556 | [-0.166667, +0] | — | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| answerable_pair/low_grounding_handoff_rate | 19 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0.65 | 0.6 | -0.05 | [-0.15, +0] | 1 | no significant change |
| half_answerable/answers_with_any_unsupported_claim | 12 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/claims_removed_per_answer | 12 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| half_answerable/low_grounding_handoff_rate | 13 | 0 | 0.0769231 | +0.0769231 | [+0, +0.230769] | 1 | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0.65 | 0.6 | -0.05 | [-0.15, +0] | 1 | no significant change |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
