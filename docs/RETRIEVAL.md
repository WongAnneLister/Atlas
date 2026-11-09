# Retrieval

## Chunking & index

Run `make up`, then `make ingest`. Inspect `data/processed/chunks.jsonl` locally.
`make ingest-chunks` runs the real pinned BGE tokenizer without loading model weights or Milvus.
Optional `make embedding-cache` prefetches model files without loading the encoder.
`make test-milvus` runs the integration test explicitly; normal unit tests remain offline.
`make eval-ingest` regenerates the counts and records the actual ingestion/integration status.

Documents split at section markers first; policy chunks never cross a section boundary.
Within a long section, paragraph endings are preferred, then sentence endings, then token offsets.
Overlapping source windows retain the configured number of tokens within each section.
Token counts use the pinned BGE fast tokenizer, excluding special tokens and heading prefixes.
Product sections always remain a single chunk, even when an entire manual exceeds the policy budget.
Source text and section ids remain unchanged; the frozen evaluation set is not rewritten.
Chunk ids hash section id and its local chunk index. Full rebuilds remove obsolete rows.
Heading paths are prepended only to encoder input when enabled; displayed and BM25 text stay raw.

Model files are cached under the configured gitignored cache directory at a pinned revision.
If Xet downloads stall, set `HF_HUB_DISABLE_XET=1` before running `make embedding-cache`.
For long encoder inputs, bounded source windows cover all tokens without truncation.
Their dense vectors are averaged by window token count and then normalised when configured.
This keeps long products intact while bounding encoder memory; quality must be measured later.
Batch size, device, precision, thread count and window size are configuration values.

The collection uses HNSW/COSINE dense vectors and a sparse BM25 function generated from text.
The text analyzer is enabled; callers never send hand-built sparse vectors.
All Milvus SDK imports are isolated in `milvus_store.py`.
UTF-8 byte lengths, vector shape and finite values are checked before collection replacement.
Reset refuses a collection lacking this project's description marker.
The pipeline checks server connectivity before downloading weights; it embeds before resetting data.
Index promotion and transactional incremental updates belong to the later production phase.

Compose works with either the Docker plugin or official standalone docker-compose CLI.
On a host without the app environment, use `make up COMPOSE_PYTHON=python3` for Compose only.
MinIO is built from its original fixed source commit because community images were withdrawn.
The first build needs network access; later starts reuse the local image and build cache.
The source build keeps the upstream license and credits inside the image.
If a remote daemon lacks build space, put official Go 1.23.4 on the client PATH.
Run `make minio-image-local` there, then `make up`; only the small runtime image is sent.
Set `MINIO_TARGET_ARCH` to match the Docker server; the local build defaults to amd64.
The core containers have configurable memory limits in `docker-compose.yml`.
Published Milvus ports bind to loopback. For a remote Docker context, forward the ports over SSH.
The client URI remains configurable; never assume a remote Docker daemon is the local host.
No unrelated containers are stopped. Only the configured project collection is reset by ingestion.

References: [Milvus full text search](https://milvus.io/docs/v2.5.x/full-text-search.md),
[BGE-M3 model card](https://huggingface.co/BAAI/bge-m3).
MinIO build context: [upstream distribution change](https://github.com/minio/minio#source-only-distribution).

## Hybrid + RRF

Run `make search Q="Does the W40 come with a charger?" MODE=hybrid` to inspect results.
Modes are `dense`, `bm25`, and `hybrid`; `hybrid_rerank` raises until commit 08.
The command prints section ids, chunk ids, heading paths, source ranks and scores.
It only retrieves evidence; it does not write a customer answer or bypass the future gate.
Use a model present in the rebuilt catalog, such as `BHD340/10`, for product checks.
W40 is the task's example spelling, not a product added to this corpus.
A returned chunk alone does not prove that an absent product or attribute is supported.

`RetrievedChunk` retains every indexed chunk field, plus separate `scores` and `ranks` maps.
Dense retrieval embeds the original query using the same pinned BGE-M3 encoder as ingestion.
BM25 sends query text to Milvus's existing full-text function; it never builds sparse vectors locally.
The factory accepts an injected store and embedder for offline tests or shared connections.
Applications should own an injected `MilvusStore` and close it when finished, as the CLI does.

Hybrid retrieval requests `retrieval.dense_top_k` and `retrieval.bm25_top_k` candidates independently.
Both default to 50. Retrieval is sequential; either dependency failure propagates without partial results.
Reciprocal Rank Fusion (RRF) adds `1 / (rrf_k + rank)` for each occurrence across sources.
Ranks begin at one; an absent source contributes nothing. Raw scores are not mixed.
Equal fusion scores use the best single source rank, then chunk id, for deterministic ordering.
Duplicate ids within one source ranking are rejected instead of counted twice.
The merged results retain both source ranks and raw scores, with the fused score under `scores.rrf`.
The caller supplies its output limit; the debug CLI uses `retrieval.search_top_k` from YAML.

RRF avoids comparing cosine similarity with BM25 scores on different scales.
The configured `rrf_k` is 60, following the pilot choice in the
[original RRF paper](https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf).
This is a starting default, not a measured optimum for this corpus.
Any later sweep must tune on dev and report on test; commit 08 measures retrieval quality.

`retrieval.bm25_normalise_model_numbers` enables query-only spelling cleanup by default.
It case-folds text and joins a letter prefix to digits across a hyphen: `W-40` becomes `w40`.
It preserves suffixes such as `/00`, amounts such as `30`, and ordinary hyphenated words.
Dense queries, indexed source text, model facts and frozen eval labels remain unchanged.
Disable this flag to compare with raw BM25 queries in commit 08.
The normaliser does not claim to fix every catalog spelling or establish a quality gain.

## Measured ingestion

# Chunking and ingestion report

Generated by `make eval-ingest`. Do not edit by hand.

- Git SHA (base revision when run): `dee401470c0f9ba229179d29e7176c98adcaa2aa`
- Retrieval code hash: `80f36b12a8610335629f4a6470b1505121ce17506b059db87b593efdf5b8825f`
- Config hash: `11d43834a603327136967f25af7d6a3416828a8b3f3908655764196dbf177aa8`
- Corpus hash: `3297ff909f59f3d1b242eb9cc3d3dd2db3cf88fd447ec509c8571f6465203577`
- Chunk hash: `ad12a4a666183da02b64b933c16e17f343a01501a9c3eaa5d58ebb954db13169`
- Date (UTC): 2026-11-09
- Tokenizer/model: `BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181`
- Reranker (not loaded): `BAAI/bge-reranker-v2-m3`
- Runtime packages: FlagEmbedding 1.4.2, transformers 5.22.2, pymilvus 3.0.2
- Dataset version: processed docs from pinned raw sources listed below.
- Eval split: not applicable; full-corpus ingestion integrity, no quality tuning.

## Actual run status

- Status: `complete`
- Milvus server: `2.5.10`
- Stored rows: 206
- Encoder windows evaluated: 244
- Manual integration test: 1/1 passed (real-server test; fake vectors)
- Error: none

## Source chunk counts

| Measure | Value |
|---|---:|
| documents | 12 |
| sections | 122 |
| chunks | 206 |
| policy chunks | 199 |
| whole product chunks | 7 |
| average body tokens | 491.43 |
| maximum body tokens | 12331 |
| maximum policy body tokens | 512 |
| configured policy budget | 512 |
| configured overlap | 64 |
| configured encoder window including special tokens | 1024 |

| Document | Chunks |
|---|---:|
| catalog_air_fryers | 1 |
| catalog_hair_dryers | 3 |
| catalog_headphones | 1 |
| catalog_monitors | 2 |
| membership | 38 |
| orders | 22 |
| other | 37 |
| payments | 39 |
| refunds | 11 |
| returns | 18 |
| shipping | 21 |
| warranty | 13 |

## Timings

- chunking: 9.052 seconds
- embedding_and_ingestion: 776.098 seconds
- total: 794.952 seconds

## Dataset revisions

- bitext: `bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443`
- flipkart_faqs: `NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228`
- maktek_faqs: `MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240`
- philips_manuals: `InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84`

A chunk-only or failed run is not proof of real embedding or successful Milvus ingestion.
The integration fixture checks database behavior; it does not measure BGE quality.
