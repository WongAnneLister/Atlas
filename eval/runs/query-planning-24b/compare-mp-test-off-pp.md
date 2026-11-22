# Eval run comparison

- Run A: `/tmp/atlas-24b/runs/multipart-test-20261122-b864da21-6bdbc4adfb494004b31164dc2d4c9f60`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `640e4ff272e20ce775f7653b792b82e98cdce8d6ef95f4ac1b9f9aa866bf85c1`
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
| full_answer_rate | 20 | 0.85 | 0.9 | +0.05 | [+0, +0.15] | 1 | no significant change |
| latency_p50 | 50 | 17.466 | 21.411 | +3.94499 | [+2.73402, +5.25312] | — | worse |
| latency_p95 | 50 | 20.8664 | 27.7635 | +6.89715 | [-10.3497, +16.0757] | — | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0 | 0.26 | +0.26 | [+0.14, +0.38] | 0.0002441 | better |
| pass_rate | 50 | 0.34 | 0.36 | +0.02 | [+0, +0.06] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.85 | 0.9 | +0.05 | [+0, +0.15] | 1 | no significant change |
| answerable_pair/latency_p50 | 20 | 18.1311 | 21.3775 | +3.24645 | [+2.47048, +6.02959] | — | worse |
| answerable_pair/latency_p95 | 20 | 20.8201 | 25.4032 | +4.58312 | [-10.3497, +5.02937] | — | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.85 | 0.9 | +0.05 | [+0, +0.15] | 1 | no significant change |
| both_unanswerable/latency_p50 | 10 | 14.6155 | 20.9447 | +6.32912 | [+0.992685, +9.38909] | — | worse |
| both_unanswerable/latency_p95 | 10 | 20.6864 | 22.5132 | +1.82676 | [+0.892639, +5.0472] | — | worse |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0 | 0.65 | +0.65 | [+0.45, +0.85] | 0.0002441 | better |
| half_answerable/latency_p50 | 20 | 17.4017 | 22.4191 | +5.01741 | [-1.74538, +6.78404] | — | no significant change |
| half_answerable/latency_p95 | 20 | 20.8664 | 27.7635 | +6.89715 | [-1.96195, +17.6659] | — | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0 | 0.65 | +0.65 | [+0.45, +0.85] | 0.0002441 | better |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
