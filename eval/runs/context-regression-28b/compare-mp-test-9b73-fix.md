# Eval run comparison

- Run A: `/tmp/atlas-r35/runs/multipart-test-20261126-9b7350e6-7952421bee4b4ecaaf56cf66891b2257`
- Run A Git SHA: `9b7350e6728f2c6365c6fd78569c1e72182b7670`
- Run A config hash: `06b38d52beeeb654770d5098df42cd0ad24b07f605653294706e2e0f0008d438`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/runs/multipart-test-20261126-9bbd3648-95ac86702e6c41e99f8f4beaff6c543f`
- Run B Git SHA: `9bbd3648603b4fa8fa71782cc48bf81340479616`
- Run B config hash: `3ca0e3556a29dcfb3705b83678c0710ba7fede75b8438c856995fb124a16e92a`
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
| answered_part_correct | 20 | 0.6 | 0.55 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| answers_with_any_unsupported_claim | 29 | 0 | 0.0689655 | +0.0689655 | [+0, +0.172414] | 0.5 | no significant change |
| claims_removed_per_answer | 29 | 0 | 0.0689655 | +0.0689655 | [+0, +0.172414] | — | no significant change |
| full_answer_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| low_grounding_handoff_rate | 31 | 0.0322581 | 0.0322581 | +0 | [-0.0967742, +0.0967742] | 1 | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0.24 | 0.22 | -0.02 | [-0.0805, +0.04] | 1 | no significant change |
| pass_rate | 50 | 0.36 | 0.36 | +0 | [-0.06, +0.06] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/answers_with_any_unsupported_claim | 18 | 0 | 0.0555556 | +0.0555556 | [+0, +0.166667] | 1 | no significant change |
| answerable_pair/claims_removed_per_answer | 18 | 0 | 0.0555556 | +0.0555556 | [+0, +0.166667] | — | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| answerable_pair/low_grounding_handoff_rate | 19 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.9 | 0.9 | +0 | [-0.15, +0.15] | 1 | no significant change |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0.6 | 0.55 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| half_answerable/answers_with_any_unsupported_claim | 11 | 0 | 0.0909091 | +0.0909091 | [+0, +0.272727] | 1 | no significant change |
| half_answerable/claims_removed_per_answer | 11 | 0 | 0.0909091 | +0.0909091 | [+0, +0.272727] | — | no significant change |
| half_answerable/low_grounding_handoff_rate | 12 | 0.0833333 | 0.0833333 | +0 | [-0.25, +0.25] | 1 | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0.6 | 0.55 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
