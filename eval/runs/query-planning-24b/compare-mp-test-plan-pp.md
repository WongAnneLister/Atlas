# Eval run comparison

- Run A: `/tmp/atlas-24b/runs/multipart-test-20261122-b864da21-eb8a5eab2dda4345acdbdd02c108526d`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `15e4287b62a75f4fda0ddcd006a35c430f8cf50e19cf9e889e5cc6320650019f`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs/multipart-test-20261122-b864da21-bd4771a5cef74b64b1ca58428b680bdd`
- Run B Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run B config hash: `685145093d902001fd07f2f073dcc05df3c76236fa8ea2d8c92b1d43e6fc538b`
- Run B datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 50
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answered_part_correct | 20 | 0 | 0.65 | +0.65 | [+0.45, +0.85] | 0.0002441 | better |
| full_answer_rate | 20 | 0.95 | 0.9 | -0.05 | [-0.15, +0] | 1 | no significant change |
| latency_p50 | 50 | 20.2404 | 21.411 | +1.17054 | [-0.427599, +2.42978] | — | no significant change |
| latency_p95 | 50 | 26.3043 | 27.7635 | +1.45928 | [-8.56109, +10.9257] | — | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0 | 0.26 | +0.26 | [+0.14, +0.38] | 0.0002441 | better |
| pass_rate | 50 | 0.38 | 0.36 | -0.02 | [-0.06, +0] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.95 | 0.9 | -0.05 | [-0.15, +0] | 1 | no significant change |
| answerable_pair/latency_p50 | 20 | 20.6541 | 21.3775 | +0.723467 | [-1.43761, +2.47057] | — | no significant change |
| answerable_pair/latency_p95 | 20 | 35.0334 | 25.4032 | -9.6302 | [-11.1553, +1.70804] | — | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.95 | 0.9 | -0.05 | [-0.15, +0] | 1 | no significant change |
| both_unanswerable/latency_p50 | 10 | 19.559 | 20.9447 | +1.38564 | [-3.50942, +2.91261] | — | no significant change |
| both_unanswerable/latency_p95 | 10 | 24.9863 | 22.5132 | -2.47309 | [-3.40721, +0.00872021] | — | no significant change |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0 | 0.65 | +0.65 | [+0.45, +0.85] | 0.0002441 | better |
| half_answerable/latency_p50 | 20 | 19.7315 | 22.4191 | +2.68763 | [-3.44375, +5.1759] | — | no significant change |
| half_answerable/latency_p95 | 20 | 25.9701 | 27.7635 | +1.79349 | [-1.36218, +13.426] | — | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0 | 0.65 | +0.65 | [+0.45, +0.85] | 0.0002441 | better |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
