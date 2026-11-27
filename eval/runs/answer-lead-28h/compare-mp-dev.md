# Eval run comparison

- Run A: `/tmp/atlas-r35/lead/runs/multipart-dev-20261127-dfe8c4f4-78907811e8184bd49307db4e0a68d6b9`
- Run A Git SHA: `dfe8c4f4af871d96cc26c96f6879fd9f02ef3f57`
- Run A config hash: `2dd662a2beaf9f9e55598c74e9c9eb9c2103761d91d5816345a688f0fd4f929e`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-r35/lead/runs/multipart-dev-20261127-dfa1aa54-925712a21077444f8482e08758e98b85`
- Run B Git SHA: `dfa1aa548a6e442e67bcec7494249037b47f7b3a`
- Run B config hash: `06392996efaad7f1ae89f3a8a0b5593567f69a7e8188f1b6c3ea3fe66abf3302`
- Run B datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run B split: dev
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 50
- Only in A: 0
- Only in B: 0
- Latency not compared: a run collected items concurrently (workers 3, 3).

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answered_part_correct | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| answers_with_any_unsupported_claim | 33 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| claims_removed_per_answer | 33 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| full_answer_rate | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| low_grounding_handoff_rate | 33 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0.34 | 0.34 | +0 | [-0.06, +0.06] | 1 | no significant change |
| pass_rate | 50 | 0.32 | 0.34 | +0.02 | [+0, +0.06] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/answers_with_any_unsupported_claim | 17 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/claims_removed_per_answer | 17 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| answerable_pair/low_grounding_handoff_rate | 17 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0.05 | 0 | -0.05 | [-0.15, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| half_answerable/answers_with_any_unsupported_claim | 16 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/claims_removed_per_answer | 16 | 0 | 0 | +0 | [+0, +0] | — | no significant change |
| half_answerable/low_grounding_handoff_rate | 16 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0.8 | 0.85 | +0.05 | [+0, +0.15] | 1 | no significant change |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
