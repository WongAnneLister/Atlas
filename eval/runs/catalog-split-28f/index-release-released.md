# Index release — Release


- Candidate collection: support_chunks_b369f54d628024743b0bc6d5217dec566
- Git SHA: 00114f5e3b95e48b54acfb1517bcd05d61785709
- Config hash: f330440f1590a652b04e53b9f33abd8acdc27b765741f21273fc3cf49dcc677a
- Split: dev-smoke
- UTC date: 2026-11-27 09:10:59.012807+00:00
- Models: BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181, BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
- Dataset versions: {'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9'), 'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}

- gate_pass: 160/160 · 100.00% [100.00%, 100.00%]
- hit_at_5: 160/160 · 100.00% [100.00%, 100.00%]
- noanswer_gate_pass: 1/60 · 1.67% [0.00%, 5.00%]
- rr_at_5: 0.9906 [0.9781, 1.0000]

- Note: These no-answer items already pass the gate on the live build; a later check, not this one, stops them: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| hit_at_5 | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| rr_at_5 | 160 | 0.990625 | 0.990625 | +0 | [+0, +0] | — | no significant change |
| gate_pass | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_gate_pass | 60 | 0.0166667 | 0.0166667 | +0 | [+0, +0] | 1 | no significant change |
