# Retrieval

## Chunking & index

Run `make up` and prepare the registered release datasets before `make ingest`. Inspect
`data/processed/chunks.jsonl` locally after building.
`make ingest-chunks` runs the real pinned BGE tokenizer without loading model weights or Milvus.
Optional `make embedding-cache` prefetches model files without loading the encoder.
`make test-milvus` runs the integration test explicitly; normal unit tests remain offline.
`make eval-ingest` regenerates the counts and records the actual ingestion/integration status.

Documents split at section markers first; policy chunks never cross a section boundary.
Within a long section, paragraph endings are preferred, then sentence endings, then token offsets.
Overlapping source windows retain the configured number of tokens within each section.
Token counts use the pinned BGE fast tokenizer, excluding special tokens and heading prefixes.
A product section up to `chunk.product_whole_max_tokens` (4096, half the verify budget) remains a
single chunk. A longer one (a whole manual) is cut with the policy budget and overlap since chunker
version 3 (28e); with `chunk.product_window_header` each window starts with the product heading,
because the reranker and the gate read only chunk text. Version 2 split every product section over
512 tokens and was refused at release (28d). The measured ingestion section below predates both.
Current sections retain their source text and IDs. Synthetic history has separate IDs.
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
Index promotion uses the lifecycle below.

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
No unrelated containers are stopped. Ingestion creates a private candidate collection.

References: [Milvus full text search](https://milvus.io/docs/v2.5.x/full-text-search.md),
[BGE-M3 model card](https://huggingface.co/BAAI/bge-m3).
MinIO build context: [upstream distribution change](https://github.com/minio/minio#source-only-distribution).

## Index lifecycle

The default serving name is the Milvus alias `support_chunks_live`. The registry records the
serving and previous builds. A build owns an immutable collection and a snapshot of its sections.

```mermaid
flowchart LR
    Docs["Policy documents"] --> Plan["Compare with serving sections"]
    Plan --> Build["Build a new collection"]
    Build --> Check["Compare retrieval and check no-answer items"]
    Check -->|Pass| Live["Move serving alias"]
    Check -->|Refuse| Hold["Keep current alias"]
    Live -->|Rollback| Prior["Restore previous target"]
```

- `make index-plan` reports added, changed, deleted and unchanged section IDs without contacting
  Milvus. It compares with the serving build, so rollback and unreleased builds do not move the
  comparison point. Add `INDEX_ARGS='--docs-dir /path/to/scratch-docs'` to use a scratch corpus.
- Every change builds a new collection. Incremental builds encode added and changed sections and
  copy verified dense vectors for unchanged chunks. A changed encoding or chunking fingerprint
  triggers a full build. The fingerprint includes the embedding profile, chunk settings and
  schema versions. `make index-build INDEX_ARGS=--full` forces a full rebuild.
- `make index-release BUILD=<id>` compares raw-query retrieval and evidence-gate outcomes on
  the frozen dev and knowledge smoke sets. It pairs hit, reciprocal rank and gate outcomes against
  the serving build and reuses compatible saved evidence. This is an index check. CI still covers
  rewritten queries, full graph behavior and red-team cases. The CPU reranker dominates its cost
  because the check reranks each question. `INDEX_ARGS=--reranker-device=mps` can select that device
  for the evidence run.
- Every dev no-answer item must fail the evidence gate (`index.release.absolute_splits`); the
  gate threshold was tuned on dev. A test-split no-answer item may pass the gate only if it also
  passes on the live build: the serving index passes one at the gate today, and the LLM coverage
  check stops it later in the app. A first release has no live build, so it judges dev only and
  lists other passes. An unassessed candidate no-answer item also prevents release.
  Each question retries a Milvus transport failure under `index.release.retry`; other errors
  are recorded at once. Runs above the configured retrieval-error limit are invalid. A paired regression may be
  overridden with a written `--override-reason`; the registry and report retain it. It cannot
  override a no-answer rule or an invalid run. Matching clean evidence for a build is reused
  as either the live or the candidate side.
- `make index-adopt COLLECTION=support_chunks` verifies on-disk chunks against the existing index
  and registers it without changing its rows. Adoption establishes text equivalence and assumes the
  supplied embedding settings describe the existing vectors. It is for bootstrapping the current
  index and skips the release evaluation. On an empty deployment, `make ingest` builds and checks
  the first index without a live comparison. Once an alias exists, the same command builds and
  runs the paired check. Local SQLite creates its registry tables on the first lifecycle write.
  For the PostgreSQL backend, run the Atlas migration before using the lifecycle commands.
- `make index-rollback` restores the previous released collection. After an embedding change,
  run the application with the embedding settings for the serving build. The paired check uses
  each build's recorded embedding profile. `make index-status` compares Milvus with the registry.
  After a verified interrupted switch, `INDEX_ARGS=--reconcile` records the known Milvus target.
- `make index-gc` is a preview. `INDEX_ARGS=--yes` deletes only eligible registry-owned builds
  with the configured prefix. The live and previous targets, adopted collections and the
  registered experiment collection names are protected. Failed builds never take one of the
  `index.keep_builds` rollback slots. Release, rollback and GC serialize their alias operations
  through the registry. The release check runs before that lock is taken, because it can run for
  an hour on CPU and the registry shares its database with orders and refunds. After the check,
  the switch takes the lock and refuses if the alias moved in the meantime.
- Per-build chunk text and its checksum live under the configured builds directory. The legacy
  `chunks.jsonl` and `ingest_run.json` describe the last completed build. Cached rank readers
  require matching build provenance. `make ingest-chunks` writes its artifacts and report
  to the local preview directory.
  Serving searches follow the alias. Build ID telemetry may lag within the configured lookup TTL.
  Retrieval benchmarks that hydrate local text pin their starting target for the entire run.
- Standard retrieval evaluation starts from the alias. Ablations use the two configured experiment
  collections. The experiment builder may rebuild only those two, after opting in on its own store.
  The lifecycle (build, release, GC, adoption) can never write to or drop them.
- Offline tests use scratch registries and fake dependencies. The Milvus freshness, alias and
  PostgreSQL registry checks are integration tests. Live evidence for adoption, a full rebuild,
  a negative control, a one-section change and rollback is in `eval/reports/index_lifecycle.md`
  (`make eval-index-lifecycle`).


## Policy dates and product categories

`make data-docs` writes a metadata entry for every section in `section_metadata.json`.
Chunks carry document type, topic, product category, region and validity dates. The index planner
hashes section metadata with the text and heading. A metadata edit therefore marks the section as
changed. Schema version 2 forces a full build before a new release. The old serving build can still
be read during the paired check, and an alias rollback can still return to it.

The current generic-store returns and price-adjustment sections keep their text and IDs, preserving
the v1 labels. An invented historical section gets an `@2026-01-01` ID suffix and a
`(policy before 2026-09-01)` heading suffix. The historical windows are 90 days for returns and 14
days for price adjustments. The existing current windows are 30 and 7 days, respectively.
The new versions start on September 1, 2026. Other sections are valid from the configured
January 1, 2026 default. Validity includes the start day and excludes the end day.

Milvus stores dates as INT32 `YYYYMMDD` and uses `policy_versions.open_end_day` for an open end.
It indexes date fields with STL_SORT and metadata strings with INVERTED. The Python representation
uses a date or `None` for the end. Both dense and BM25 search apply the same expression before
fusion and reranking. Store scope still applies to the reranked pool.

The knowledge path uses `orders.today`. An unambiguous category comes from configured terms or
a recognized catalog model code. A category filter preserves policy chunks and keeps catalog
chunks in that category. Ambiguous or absent categories leave date filtering in place.
The refund path uses the verified purchase date from OrderService. Customer text supplies neither
date. A cited historical refund policy produces a notice from a graph template before output checks.

A schema check and both filtered searches use the same physical collection. Legacy collections
hold the current text and do not support filter fields. Run rows and graph state record
`filters_applied: false` for those searches. An empty filtered result on a metadata-enabled
collection goes through the existing evidence gate with empty evidence and hands off.

The retrieval ablations compare `off`, `date`, and `date_category` on the same index. This measures
candidate filtering before the reranker, which orders the surviving candidates by relevance.
Release and sweep evidence hashes include filter settings. The rerank pair cache keeps the same
model, query and passage key, so each ablation can reuse scores for its surviving pairs.

## Hybrid + RRF

Run `make search Q="Does the W40 come with a charger?" MODE=hybrid` to inspect results.
Modes are `dense`, `bm25`, `hybrid`, and `hybrid_rerank`.
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

## Cross-encoder reranking and evaluation

`hybrid_rerank` scores the configured fused candidate pool with the pinned BGE cross-encoder.
The model reads the original query together with each chunk body, in configured batches.
The wrapper returns at most `retrieval.rerank_top_k`, retaining component scores and ranks.
`scores.rerank_logit` is the raw model output; `scores.rerank` is its sigmoid transform.
A sigmoid score is not a calibrated probability that an answer is supported.
Invalid/nonfinite outputs or dependency errors propagate; there is no partial fallback.
The future evidence gate remains responsible for deciding whether an answer may be generated.

Model revision, device, precision, batch size, token limit and candidate/output depths live in YAML.
`make reranker-cache` prefetches the pinned model; `HF_HUB_OFFLINE=1` uses local files afterward.
The cross-encoder uses only the configured query/passage token budget.
Long manuals remain whole source chunks, but the model truncates their scored input.
This limitation is recorded in the report and can cause missed evidence later in a manual.
See the [upstream model card](https://huggingface.co/BAAI/bge-reranker-v2-m3) for raw-logit scoring.

After `make data-docs`, `make eval-build`, and `make ingest`, run `make eval-retrieval`.
The default test run also measures dev. Use `SPLIT=dev` for development or `SPLIT=all` for both.
The baseline modes measure the serving index. The heading ablation runs by default
(`retrieval_eval.run_ablations`); `EVAL_RETRIEVAL_ARGS=--no-ablations` skips it.
Both copies use identical chunks, model revision, encoder settings and index configuration.
The demo collection is preserved. Model-number cleanup is disabled only for its own row.
Both ablations compare against hybrid without reranking, holding the remaining settings fixed.
`make eval-retrieval-index` can prepare both experiment collections ahead of the experiment.
Verified vector caches survive interrupted database writes without repeating model encoding.
Index fingerprints bind the source chunks, heading flag, model settings, index settings and runtime.
Only a matching collection identity and complete matching chunk snapshot can reuse an index.
Snapshot validation reads bounded pages to keep large manual responses within the RPC deadline.

The runner validates the frozen eval manifest and compares index metadata/text with local chunks.
Only answerable items contribute to retrieval metrics; no-answer safety is measured in later commits.
Recall measures the fraction of unique gold sections in the first k chunks.
Repeated chunks from one section consume ranking slots. MRR uses the same output cutoff for all modes.
Cross-document hit_all separately checks that every required section appears.
The frozen draft benchmark is still awaiting human review; scores do not establish answer reliability.

Results are cached by mode, configuration, question, execution code, runtime, eval file and index identity.
Local cache files retain source text; committed CSVs contain ids/ranks/metrics without questions or text.
Latency sums original sequential component times, excluding model loading and index construction.
Cache hits preserve those measured times; cached lookup speed is never presented as model speed.
The evaluator reuses fully verified local chunk text after loading each index snapshot.
Milvus still computes every changed ranking; it returns ids and scores for local text hydration.
An unknown returned id raises an error. The default interactive search still fetches text from Milvus.
Reported latency excludes the initial snapshot load and describes this warm evaluation setup.
The heading ablation holds BM25 fixed; the normaliser ablation holds dense results fixed.
`make eval-failures MODE=hybrid_rerank` prints dev misses with questions, gold and retrieved headings.
Inspect dev failures when the target is missed. Keep test labels and settings frozen.
`make eval-retrieval EVAL_RETRIEVAL_ARGS=--report-only` regenerates reports from the local saved run.
The local measured run uses MPS for reranking and CPU for query/document embeddings.
The default remains CPU for portability; select an available device with an environment override.
To reproduce that execution setup, forward local port 19531 to Milvus port 19530.
The measured connection used SSH compression (`ssh -C`) with the server's configured SSH port.

```bash
HF_HUB_OFFLINE=1 \
SUPPORT_AGENT__MILVUS__URI=http://127.0.0.1:19531 \
SUPPORT_AGENT__RETRIEVAL__RERANKER_DEVICE=mps \
make eval-retrieval
```

## Retrieval experiment

Source: eval/reports/retrieval.md

| Mode | Group | n | Recall@1 | Recall@3 | Recall@5 | MRR@5 | cross_doc hit_all@5 | mean latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| dense | overall | 120 | 0.7375 | 0.9292 | 0.9667 | 0.9125 | 0.7333 | 3.1413 |
| bm25 | overall | 120 | 0.6875 | 0.9625 | 0.9875 | 0.9028 | 0.9000 | 0.4806 |
| hybrid | overall | 120 | 0.7792 | 0.9583 | 0.9917 | 0.9458 | 0.9333 | 3.6229 |
| hybrid_rerank | overall | 120 | 0.8667 | 0.9833 | 1.0000 | 0.9938 | 1.0000 | 10.2582 |
| hybrid_heading_off | overall | 120 | 0.7583 | 0.9417 | 0.9792 | 0.9299 | 0.8667 | 3.8068 |
| hybrid_normaliser_off | overall | 120 | 0.7792 | 0.9583 | 0.9917 | 0.9458 | 0.9333 | 3.6066 |
| hybrid_rerank_filters_off | overall | 120 | 0.8667 | 0.9833 | 1.0000 | 0.9938 | 1.0000 | 10.2582 |
| hybrid_rerank_filters_date | overall | 120 | 0.8667 | 0.9833 | 1.0000 | 0.9938 | 1.0000 | 8.2425 |
| hybrid_rerank_filters_date_category | overall | 120 | 0.8667 | 0.9833 | 1.0000 | 0.9938 | 1.0000 | 8.8620 |

## What this means

Recall measures gold-section coverage; MRR measures the first useful result.
Hybrid + rerank test Recall@5 meets the configured 95% target; results are reported unchanged.
No-answer items are excluded; this experiment does not establish answer safety.

## Dev failure patterns

- Cross-document questions recover only part of the required evidence: 2 dev misses; example `cross_doc-02fb4ef75dd609300f08f3052872346051d9d67ef719353e5762ea90bd46bf53`.

These draft-set results are not evidence of safe answer acceptance.

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
