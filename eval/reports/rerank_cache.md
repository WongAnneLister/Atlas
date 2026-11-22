# Rerank score cache on a one-section change

- Report git SHA: 904f6ae5d703d3e102e6afb8892b8b50106128af
- Run git SHA: 904f6ae5d703d3e102e6afb8892b8b50106128af (dirty: True)
- Evidence config hash: 374709e84c56206d4def377006c45d0aa321d1e4ae38e63626d4bc9b8126655a
- Models: BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181, BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
- Dataset versions: eval_v1 v1 (`fe82c904801b`), smoke v1 (`9ed7c618bd6e`)
- Eval split: dev-smoke
- Reranker device: mps
- Live collection: `support_chunks_bf66917e90d854635a44dbdac16e6e4c1`
- Candidate collection: `support_chunks_bef8bc336eb7d4e00946007771ff96a1b`
- Measured: 2026-11-22 UTC, three runs in order, one at a time
- Score key profile: `{"batch_size": 4, "device": "mps", "max_tokens": 512, "model": "BAAI/bge-reranker-v2-m3", "packages": {"FlagEmbedding": "1.4.2", "torch": "2.15.0", "transformers": "5.22.2"}, "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "use_fp16": false}`

Wall clock is the run manifest's start to end: model loading, Milvus search over the SSH tunnel, reranking and the gate. The cache file started empty.

| Run | Minutes | Pairs from cache | Pairs scored | Items with errors | Items retried |
|---|---:|---:|---:|---:|---:|
| Live collection, cache on (cold; fills the cache) (`support_chunks_bf66917e90d854635a44dbdac16e6e4c1`) | 28.6 | 0 | 11000 | 0/220 | 0 |
| Candidate collection, cache off (`support_chunks_bef8bc336eb7d4e00946007771ff96a1b`) | 25.8 | 0 | 11000 | 0/220 | 0 |
| Candidate collection, cache on (warm) (`support_chunks_bef8bc336eb7d4e00946007771ff96a1b`) | 6.6 | 10915 | 85 | 0/220 | 0 |

## Candidate: cache on against cache off

- Wall clock: 25.8 min without the cache, 6.6 min with it (19.1 min saved, 3.9x faster).
- Pairs reused: 10915/11000 (99.23%); scored again: 85.
- Cold run cost: the live run filled the cache in 28.6 min. It is a different collection, so it is context, not a paired measurement.
- Rows identical (metrics, top-5 chunk ids, gate score, errors): 216/220
- Rows that differ, and the fields that differ:
  - `basic_policy-3fe90dfca6700c5e888d2f4d542a7474002341c421b6288a81fc4067c1e13e25`: gate_score
  - `colloquial-4fd57cb7dc376f66d6964f2dd310c9867f118085fe6fc4ca9237bb2a6a8a6eef`: gate_score
  - `colloquial-bddd6e74373b51653ac54924eb734b4dcb66b7a15238d72b8e44e86f12af6e99`: gate_score
  - `no_answer-93f5e2700c0c65de9c01934f68afa54efb5083b34b2df895e0ab67bf2808ec40`: gate_score
- Metrics identical: 220/220; top-5 lists identical: 220/220
- Largest gate-score difference: 7.13e-09 over 220 items
- Aggregate metrics identical: True
- A cached logit is reused bit for bit. A pair scored again runs in a smaller batch than without the cache, and FlagReranker pads each batch, so its logit can differ in the last float bits. Any gate-score difference above comes from that.

| Metric | Cache off | Cache on |
|---|---|---|
| gate_pass | 160/160 · 100.00% [100.00%, 100.00%] | 160/160 · 100.00% [100.00%, 100.00%] |
| hit_at_5 | 160/160 · 100.00% [100.00%, 100.00%] | 160/160 · 100.00% [100.00%, 100.00%] |
| noanswer_gate_pass | 1/60 · 1.67% [0.00%, 5.00%] | 1/60 · 1.67% [0.00%, 5.00%] |
| rr_at_5 | 0.9906 [0.9781, 1.0000] | 0.9906 [0.9781, 1.0000] |

Run records:
- live_cold: `index-release-dev-smoke-20261122-904f6ae5-040a8c321b384467a9256f21febf1722`
- candidate_uncached: `index-release-dev-smoke-20261122-904f6ae5-7665e1c78a4e48f48698b2b1f99667df`
- candidate_warm: `index-release-dev-smoke-20261122-904f6ae5-1cc92503ea674a7f929443ccd6506d01`
