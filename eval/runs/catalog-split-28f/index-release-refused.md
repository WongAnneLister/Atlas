# Index release — Refuse

- Paired regression: rr_at_5.

- Candidate collection: support_chunks_b91f848b9ffc442e8a723fce164a9f035
- Git SHA: 9a9ac2d20bcf825dc247e7c7f8f792d01f0cc174
- Config hash: f330440f1590a652b04e53b9f33abd8acdc27b765741f21273fc3cf49dcc677a
- Split: dev-smoke
- UTC date: 2026-11-27 08:42:38.931539+00:00
- Models: BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181, BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
- Dataset versions: {'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9'), 'smoke': DatasetVersion(version='v1', sha256='9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424')}

- gate_pass: 160/160 · 100.00% [100.00%, 100.00%]
- hit_at_5: 160/160 · 100.00% [100.00%, 100.00%]
- noanswer_gate_pass: 1/60 · 1.67% [0.00%, 5.00%]
- rr_at_5: 0.9510 [0.9250, 0.9750]

- Note: These no-answer items already pass the gate on the live build; a later check, not this one, stops them: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| hit_at_5 | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| rr_at_5 | 160 | 0.990625 | 0.951042 | -0.0395833 | [-0.0625, -0.01875] | — | worse |
| gate_pass | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_gate_pass | 60 | 0.0166667 | 0.0166667 | +0 | [+0, +0] | 1 | no significant change |

- rr_at_5: model_number-024b148af0380c9c257e1426840633f2aa330a8a05c030f05d3ec5b8cd6af7f3, model_number-035b53419cb7029858f79acb308d8a76d775c7355a37a31677e71e7c4ce5b1e5, model_number-5892b0409fe4b98b1a127476fc17d8c303d6defe4d965e890ec262316ab7edef, model_number-5f5b6fdbc10ada4b0f4308ee32fb5e5d8a0191495dc1322c8c951c7ac09462f5, model_number-62e696b8af666e6da2bc26678b60922973757f7d2b91ff93438956ecb2c153f3, model_number-89ce52328a79200209fc475bb62ba32ba7834584692e50243e6c8f65987299dc, model_number-938971d21e9d5c22bddc8ed780e20a1699b45b73dc1318226f772188d5475520, model_number-9dfbaf89a7491e6e55d5004cbed910da121c0aa1c21800021eb7627a7bd8ca30, model_number-b088de6015f4e1d1c1129782d1da3d00e40c80e62cfdff40b0c84d708b8a57e8, model_number-cb56fba60de6592781dc361a81f70e5b2e261728bdf88f039a0c750f2dda7c0a, model_number-d5fa7524c2e3b6a934cc0bda2162baf6eb33af133cad83ec7279ef7cc2ee0d95, model_number-e92d250f83eaacef2d3548b4b5f00c5d6156ba06d7d3cbd15bf625320e7a4c2b, model_number-fcf61cd5d63c371f042e52acc164fa95fff2718a112d0ca10487856c50de25c6
