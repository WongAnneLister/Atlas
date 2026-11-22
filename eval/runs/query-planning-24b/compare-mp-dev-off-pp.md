# Eval run comparison

- Run A: `/tmp/atlas-24b/runs/multipart-dev-20261122-b864da21-ce1b5b7ddc97494e8a56314ed4b3becf`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `640e4ff272e20ce775f7653b792b82e98cdce8d6ef95f4ac1b9f9aa866bf85c1`
- Run A datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs/multipart-dev-20261122-b864da21-f6d445896d61418f904f8d018330e0c6`
- Run B Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run B config hash: `685145093d902001fd07f2f073dcc05df3c76236fa8ea2d8c92b1d43e6fc538b`
- Run B datasets: `{'multipart_v1': DatasetVersion(version='v1', sha256='8344a1acfc7619ef5f4f973a9c07f98a305df6bf3f6d1b11e9c2b23ccfd9d4cc')}`
- Run B split: dev
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 50
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| answered_part_correct | 20 | 0 | 0.8 | +0.8 | [+0.6, +0.95] | 3.052e-05 | better |
| full_answer_rate | 20 | 0.85 | 0.8 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| latency_p50 | 50 | 18.3057 | 22.6009 | +4.29512 | [+2.60581, +6.34304] | — | worse |
| latency_p95 | 50 | 31.4907 | 39.3655 | +7.8748 | [-0.714867, +17.9653] | — | no significant change |
| noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 40 | 0.95 | 0.95 | +0 | [+0, +0] | 1 | no significant change |
| partial_answer_rate | 50 | 0 | 0.34 | +0.34 | [+0.22, +0.48] | 1.526e-05 | better |
| pass_rate | 50 | 0.34 | 0.32 | -0.02 | [-0.08, +0.04] | 1 | no significant change |
| unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/full_answer_rate | 20 | 0.85 | 0.8 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| answerable_pair/latency_p50 | 20 | 18.389 | 24.6478 | +6.25877 | [+3.27364, +8.02769] | — | worse |
| answerable_pair/latency_p95 | 20 | 32.0902 | 34.0036 | +1.9134 | [-1.80809, +17.9653] | — | no significant change |
| answerable_pair/part_recall_at_5 | 20 | 0.9 | 0.9 | +0 | [+0, +0] | 1 | no significant change |
| answerable_pair/partial_answer_rate | 20 | 0 | 0.05 | +0.05 | [+0, +0.15] | 1 | no significant change |
| answerable_pair/pass_rate | 20 | 0.85 | 0.8 | -0.05 | [-0.2, +0.1] | 1 | no significant change |
| both_unanswerable/latency_p50 | 10 | 22.9606 | 18.5589 | -4.40161 | [-10.9694, +3.91683] | — | no significant change |
| both_unanswerable/latency_p95 | 10 | 31.4907 | 22.6009 | -8.88981 | [-9.30489, -4.38463] | — | better |
| both_unanswerable/noanswer_false_accept | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/partial_answer_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| both_unanswerable/pass_rate | 10 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/answered_part_correct | 20 | 0 | 0.8 | +0.8 | [+0.6, +0.95] | 3.052e-05 | better |
| half_answerable/latency_p50 | 20 | 15.2203 | 22.8797 | +7.65936 | [+4.44097, +10.1778] | — | worse |
| half_answerable/latency_p95 | 20 | 29.1614 | 39.3655 | +10.2041 | [-3.77538, +23.3151] | — | no significant change |
| half_answerable/part_recall_at_5 | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/partial_answer_rate | 20 | 0 | 0.8 | +0.8 | [+0.6, +0.95] | 3.052e-05 | better |
| half_answerable/pass_rate | 20 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| half_answerable/unanswerable_part_handed_off | 20 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
