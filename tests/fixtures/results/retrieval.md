# Retrieval comparison

- Git SHA (base revision): `bbbbbbb2222222222222222222222222222222222`
- Date (UTC): 2026-01-01T00:00:00+00:00

## dev

| Mode | Group | n | Recall@1 | Recall@3 | Recall@5 | MRR@5 | cross_doc hit_all@5 | mean latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid_rerank | overall | 4 | 0.1000 | 0.1000 | 0.1000 | 0.1000 | 0.1000 | 9.0000 |

## test

| Mode | Group | n | Recall@1 | Recall@3 | Recall@5 | MRR@5 | cross_doc hit_all@5 | mean latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| dense | basic_policy | 2 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | — | 0.0000 |
| dense | overall | 4 | 0.5000 | 0.6000 | 0.7000 | 0.6500 | 0.5000 | 1.0000 |
| bm25 | overall | 4 | 0.5000 | 0.6000 | 0.7500 | 0.6000 | 0.5000 | 0.5000 |
| hybrid | overall | 4 | 0.6000 | 0.7000 | 0.8000 | 0.7000 | 0.6000 | 1.5000 |
| hybrid_rerank | overall | 4 | 0.8000 | 0.9000 | 0.9500 | 0.9000 | 0.9000 | 5.0000 |
| hybrid_heading_off | overall | 4 | 0.6000 | 0.7000 | 0.7800 | 0.6800 | 0.6000 | 1.4000 |
| hybrid_normaliser_off | overall | 4 | 0.6000 | 0.7000 | 0.7900 | 0.6900 | 0.6000 | 1.5000 |
