# Eval run comparison

- Run A: `eval/runs/time_sensitive-test-20261122-cd121855-8d29360c1abc43e6b212bfc6f486b1eb`
- Run A Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1`
- Run A config hash: `44d7d139eb5db8c1ac3a788bf36dac0eec0b4e4827cf6c16810c2275801a34a9`
- Run A datasets: `{'eval_v2': DatasetVersion(version='v2', sha256='9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8')}`
- Run A split: test
- Run A models: `{'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}`
- Run B: `eval/runs/time_sensitive-test-20261122-cd121855-c85da09ec3b548ea90fefc47fdf45d7d`
- Run B Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1`
- Run B config hash: `e6e6e7bd1e8b4642ff7b545e8f6193fffe2cf93404536501f14d5d47f5daf6c9`
- Run B datasets: `{'eval_v2': DatasetVersion(version='v2', sha256='9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8')}`
- Run B split: test
- Run B models: `{'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}`
- Shared items: 24
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| filters_applied | 24 | 0 | 1 | +1 | [+1, +1] | 1.192e-07 | better |
| gate_pass | 24 | 0.166667 | 0.166667 | +0 | [+0, +0] | 1 | no significant change |
| version_hit_at_5 | 24 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| wrong_version_at_5 | 24 | 1 | 0 | -1 | [-1, -1] | 1.192e-07 | better |
