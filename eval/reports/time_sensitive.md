# Time-sensitive policy retrieval

Generated from run records by `make eval-time-sensitive`.

Each refund row represents a distinct order date and uses the same return-policy query.
For these rows, policy version selection depends only on the stored order date.
Version hits and wrong-version hits can both occur in one row.
The gate is evaluated without an LLM. This does not measure decision or answer quality.

## time_sensitive-dev-20261122-cd121855-1f4299ba37644d5a9e674dd6b66be7ac

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `44d7d139eb5db8c1ac3a788bf36dac0eec0b4e4827cf6c16810c2275801a34a9`
- Date (UTC): 2026-11-22 07:31:22.770301+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: off. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| dev | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 24/24 100.00% [86.20%, 100.00%] | 4/24 16.67% [6.68%, 35.85%] | 0/24 0.00% [0.00%, 13.80%] |
| dev | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] |
| dev | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] |

## time_sensitive-dev-20261122-cd121855-b2787a95a19544389ffb667d1ed7e544

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `ad84397acbadddebf3441103e81d8e6c5da61a14dc444e6f46f3859ecf6d7a65`
- Date (UTC): 2026-11-22 07:37:39.638084+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: date. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| dev | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 0/24 0.00% [0.00%, 13.80%] | 4/24 16.67% [6.68%, 35.85%] | 24/24 100.00% [86.20%, 100.00%] |
| dev | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] | 20/20 100.00% [83.89%, 100.00%] |
| dev | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] |

## time_sensitive-dev-20261122-cd121855-e088b5d57edb433eb1c90a2a4b527926

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `e6e6e7bd1e8b4642ff7b545e8f6193fffe2cf93404536501f14d5d47f5daf6c9`
- Date (UTC): 2026-11-22 07:48:02.373663+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: date_category. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| dev | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 0/24 0.00% [0.00%, 13.80%] | 4/24 16.67% [6.68%, 35.85%] | 24/24 100.00% [86.20%, 100.00%] |
| dev | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] | 20/20 100.00% [83.89%, 100.00%] |
| dev | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] |

## time_sensitive-test-20261122-cd121855-8d29360c1abc43e6b212bfc6f486b1eb

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `44d7d139eb5db8c1ac3a788bf36dac0eec0b4e4827cf6c16810c2275801a34a9`
- Date (UTC): 2026-11-22 07:41:52.075227+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: off. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| test | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 24/24 100.00% [86.20%, 100.00%] | 4/24 16.67% [6.68%, 35.85%] | 0/24 0.00% [0.00%, 13.80%] |
| test | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] |
| test | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] |

## time_sensitive-test-20261122-cd121855-417e1ea18bcc4197b75f9d5e9e24693f

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `ad84397acbadddebf3441103e81d8e6c5da61a14dc444e6f46f3859ecf6d7a65`
- Date (UTC): 2026-11-22 07:44:57.659375+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: date. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| test | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 0/24 0.00% [0.00%, 13.80%] | 4/24 16.67% [6.68%, 35.85%] | 24/24 100.00% [86.20%, 100.00%] |
| test | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] | 20/20 100.00% [83.89%, 100.00%] |
| test | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] |

## time_sensitive-test-20261122-cd121855-c85da09ec3b548ea90fefc47fdf45d7d

- Git SHA: `cd1218553498c7dd22e77547e9c82cc3cf1855f1` (dirty: False)
- Config hash: `e6e6e7bd1e8b4642ff7b545e8f6193fffe2cf93404536501f14d5d47f5daf6c9`
- Date (UTC): 2026-11-22 07:51:07.054104+00:00
- Dataset: eval_v2 v2 (`9d526bd4326975dcb39818052b7d469f6c461bd4dabf385c0386ef9a023844a8`)
- Models: {'embedding': 'BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181', 'reranker': 'BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'}
- Collection: `support_chunks_live` (build: `4aece1a3ed4f4905837a125c9249857e`)
- Filters: date_category. Intervals: 95% Wilson.

| Split | Path | Items | version_hit_at_5 | wrong_version_at_5 | gate_pass | filters_applied |
|---|---|---:|---:|---:|---:|---:|
| test | all | 24 | 24/24 100.00% [86.20%, 100.00%] | 0/24 0.00% [0.00%, 13.80%] | 4/24 16.67% [6.68%, 35.85%] | 24/24 100.00% [86.20%, 100.00%] |
| test | knowledge | 20 | 20/20 100.00% [83.89%, 100.00%] | 0/20 0.00% [0.00%, 16.11%] | 0/20 0.00% [0.00%, 16.11%] | 20/20 100.00% [83.89%, 100.00%] |
| test | refund | 4 | 4/4 100.00% [51.01%, 100.00%] | 0/4 0.00% [0.00%, 48.99%] | 4/4 100.00% [51.01%, 100.00%] | 4/4 100.00% [51.01%, 100.00%] |
