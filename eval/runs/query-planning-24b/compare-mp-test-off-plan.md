# Eval run comparison

- Run A: `/tmp/atlas-24b/runs/multipart-test-20261122-b864da21-6bdbc4adfb494004b31164dc2d4c9f60`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `640e4ff272e20ce775f7653b792b82e98cdce8d6ef95f4ac1b9f9aa866bf85c1`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: test
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs/multipart-test-20261122-b864da21-eb8a5eab2dda4345acdbdd02c108526d`
- Run B Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run B config hash: `15e4287b62a75f4fda0ddcd006a35c430f8cf50e19cf9e889e5cc6320650019f`
- Run B datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run B split: test
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 50
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answered_part_correct | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| full_answer_rate | 20 | 0.85 | 0.95 | +0.1 | [+0, +0.25] | 0.5 | no significant change |
| latency_p50 | 50 | 17.466 | 20.2404 | +2.77445 | [+1.22287, +4.54036] | — | worse |
| latency_p95 | 50 | 20.8664 | 26.3043 | +5.43787 | [-9.53161, +14.347] | — | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.975 | 0.975 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 50 | 0.34 | 0.38 | +0.04 | [+0, +0.1] | 0.5 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.85 | 0.95 | +0.1 | [+0, +0.25] | 0.5 | no significant change |
| answerable_pair/latency_p50 | 20 | 18.1311 | 20.6541 | +2.52299 | [+0.928924, +5.24889] | — | worse |
| answerable_pair/latency_p95 | 20 | 20.8201 | 35.0334 | +14.2133 | [-9.53161, +15.6352] | — | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.85 | 0.95 | +0.1 | [+0, +0.25] | 0.5 | no significant change |
| both_unanswerable/latency_p50 | 10 | 14.6155 | 19.559 | +4.94348 | [+0.54471, +10.2379] | — | worse |
| both_unanswerable/latency_p95 | 10 | 20.6864 | 24.9863 | +4.29985 | [+1.14962, +6.17701] | — | worse |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/latency_p50 | 20 | 17.4017 | 19.7315 | +2.32977 | [-0.128963, +4.75617] | — | no significant change |
| half_answerable/latency_p95 | 20 | 20.8664 | 25.9701 | +5.10366 | [-3.81523, +7.30875] | — | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
