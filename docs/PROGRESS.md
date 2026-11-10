# Progress

Agents: update this file in every commit. Keep it short and factual.

## Status

| # | Commit | Status | Key numbers / notes |
|---|---|---|---|
| 01 | Scaffold | done | Skeleton, typed config, LLM factory, Milvus compose, CI, note checker. No metrics yet. |
| 02 | Data download + licenses | done | PRD main KB `qgyd2021/e_commerce_customer_service` is gone from the Hub; replaced by `NebulaByte/E-Commerce_FAQs` + `InfiniFlow` Philips PDFs. Rows (`data/raw/MANIFEST.json`): flipkart_faqs 659, philips_manuals 6 PDFs, maktek_faqs 200 (~89 unique), bitext 26,872 / 27 intents. Licenses (`docs/LICENSES.md`): flipkart + philips **unclear** (third-party text) → scripts only; maktek apache-2.0 and bitext cdla-sharing-1.0 → **yes**. |
| 03 | Policy documents | done | `eval/reports/docs_build.md`: 12 docs, 122 sections, 7 product models; FAQ coverage 856/859 (99.65%). Extractive prose, source-scoped sections, cached topics, strict fact/provenance checks, byte-identical rebuild. Processed text stays local. |
| 04 | Mock orders + OrderService | done | `eval/reports/orders_seed.md`: 50 customers, 300 orders, 749 items, 8 statuses, 14 named edge cases; 900 cross-customer operations blocked. Deterministic transactional reseed; ownership-scoped service; refund requests stay pending_review. |
| 05 | Eval set | done | `eval/reports/eval_set.md`: 300 questions, 5 groups, 30 dev + 30 test per group; 240 answerable; validator failures 0. reviewed: 0/300 — waiting for human review. Local review CSV exported; questions and labels frozen before retrieval. |
| 06 | Chunking + ingestion | done | `eval/reports/ingestion.md`: 206 chunks, 122 sections; 206 real BGE-M3 rows stored in Milvus 2.5.10; 244 encoder windows. Average 491.43 tokens; maximum 12,331 (whole manual), policy maximum 512. Database integration: 1/1 passed with fake vectors. |
| 07 | Hybrid retrieval + RRF | done | Dense/BM25 adapters, deterministic RRF, query-only model normaliser, factory and `make search`. Offline checks and real Milvus integration passed. Real BGE-M3 hybrid search and normalised BM25 both retrieved BHD340/10. No retrieval quality metrics yet. |
| 08 | Rerank + retrieval eval | done | `eval/reports/retrieval.md`, test Recall@5 / MRR@5: dense 0.9667 / 0.9125; BM25 0.9875 / 0.9069; hybrid 0.9958 / 0.9458; hybrid + rerank 1.0000 / 0.9938. Both ablations measured on dev/test. Offline checks and real Milvus integration passed. |
| 09 | Graph skeleton + intents | done | Fixed rewrite/classify/five-stub graph, typed state, memory/optional SQLite checkpoints, exhaustive Bitext mapping. `eval/reports/intent.md`: real DeepSeek intent accuracy 0.9048, path accuracy 0.9095 over 420 held-out items; parse/invocation failures 0. |
| 10 | Tool, complaint, fixed paths | done | Customer-bound read-only tools, capped main-model loop, complaint acknowledgement, local fixed replies, typed shared handoff, and `make chat`. Real DeepSeek CLI lookup verified the seeded delayed shipment through order and tracking tools. See `docs/TOOL_PATHS.md`; task-quality measurements remain in commit 13. |
| 11 | Evidence gate + knowledge path | implemented; dev analysis pending | Real dev analysis awaits local Milvus; threshold remains untuned. |
| 12 | Refund sub-flow | todo | |
| 13 | E2E eval + threshold sweep | todo | |
| 14 | API + SSE + chat page | todo | |
| 15 | Langfuse + cost | todo | |
| 16 | README + demo script | todo | |
| | **Phase 2 — production grade** | | |
| 17 | Eval platform + CI gate | todo | |
| 18 | Postgres + Redis | todo | |
| 19 | Reliability | todo | |
| 20 | Red-team set | todo | |
| 21 | Guardrails + security | todo | |
| 22 | Incremental ingestion | todo | |
| 23 | Policy versions + metadata | todo | |
| 24 | Query planning | todo | |
| 25 | Claim grounding | todo | |
| 26 | Caching | todo | |
| 27 | Multi-turn simulator | todo | |
| 28 | ContextBuilder | todo | |
| 29 | Short-term memory | todo | |
| 30 | Long-term memory | todo | |
| 31 | Handoff loop | todo | |
| 32 | Online eval + drift | todo | |
| 33 | Load test + SLO | todo | |
| 34 | Deploy + README v2 | todo | |
| 35 | Prefix-cache A/B (run after 29) | todo | |

## Latest numbers (copied from eval/reports by script or by hand with the report path)

- 03: Document build integrity: 856/859 FAQ rows covered (99.65%), 12 docs, 122 sections, 7 models (`eval/reports/docs_build.md`). No retrieval or answer-quality metrics yet.
- 04: Mock order integrity: 50 customers, 300 orders, 749 items, 192 shipments, 8 statuses, 14 named edge cases; 900 cross-customer operations blocked (`eval/reports/orders_seed.md`). These are fixture checks, not agent-quality metrics.
- 05: Eval construction: 300 items, 240 answerable; 30 dev/30 test per group; validation failures 0; reviewed: 0/300 — waiting for human review (`eval/reports/eval_set.md`). No retrieval or answer-quality measurements yet.
- 06: Real-model ingestion integrity: 206 chunks from 122 sections stored in Milvus 2.5.10, using 244 encoder windows (`eval/reports/ingestion.md`). The separate database integration fixture passed 1/1 with fake vectors. These checks do not measure retrieval quality.
- 07: Real-index smoke checks passed via SSH forwarding: BGE-M3 hybrid search for BHD340/10 and BM25 for BHD-340/10 retrieved the matching product. These are manual acceptance checks, not frozen-set quality metrics; retrieval comparison remains in commit 08.
- 08: `eval/reports/retrieval.md`: all four modes and both ablations measured on 120 dev and 120 test answerable questions. Reranked test Recall@5 is 1.0000, MRR@5 is 0.9938, and cross-document hit_all@5 is 1.0000. Mean warm-process latency is 9.4737 seconds versus hybrid's 3.7754 seconds. These are unreviewed draft-set retrieval results, not answer-safety measurements.
- 09: `eval/reports/intent.md`: DeepSeek Flash non-thinking mode measured 420 intent-holdout questions. Intent accuracy 0.9048 and path accuracy 0.9095 meet the initial target; mean original classification latency 0.7728 seconds, parse/invocation failures 0. Refund recall is only 0.7200; order-status recall is 0.7800 and human-contact recall is 0.8400. All labels remain unreviewed drafts.
- 10: No new task-quality metric yet. Offline route, identity isolation, tool failure, cap, checkpoint, and CLI checks accompany a real DeepSeek CLI smoke check against the seeded delayed shipment. Neither smoke checks nor fake-model tests establish end-to-end answer safety; that remains in commit 13.
- 11: The knowledge route now retrieves, reranks, gates, then answers with checked citations or hands off. `--allow-untuned-gate` explicitly enables the configured 0.5 demo placeholder; the production threshold remains null. `make gate-analysis` could not connect to local Milvus at `127.0.0.1:19530`, so no signal metrics or manual chat result are recorded yet.

## Checkpoints

- **Checkpoint 1 — Week 1 gate passed.** Commits 02, 03 and 04 are done. Policy documents and mock order data can be rebuilt with Makefile targets.
- **Checkpoint 2 — Week 2 gate passed — 4 configs measured.** Commit 08 includes real dev/test results and both ablations. The draft benchmark meets the retrieval target; human review and the evidence gate remain required.

## Known issues / follow-ups

- 09/10: Order tools, complaints, and fixed replies are now connected; knowledge and after-sales remain stubs. Low-confidence knowledge/after-sales predictions retain their route and receive a flag. The confidence cutoff is uncalibrated and is not an answer-safety threshold. The evidence gate remains required in commit 11.
- 10: Identity is injected from trusted state, but caller authentication and customer/thread ownership checks remain absent. Tool facts constrain the prompt; generated prose has no semantic faithfulness measurement yet. Complaint filtering is conservative text matching, not a safety proof. Handoffs are validated state records, not delivery to a persisted operator queue.
- 10: Fixed replies and immediate human requests make no model call inside their path nodes; the graph still classifies turns and rewrites follow-ups with the fast model. Internal tool messages stay within the loop; trace entries and successful facts preserve lookup context. Counters and transient fields reset each turn.
- 10: The commit prompt's order `1042` is absent from the real seed; CLI acceptance used the named delayed-tracking fixture `ORD-000009` for `CUST-0001`. Local DeepSeek credentials stay in ignored `.env`. Windows checks use `PYTHONUTF8=1` because an existing retrieval-report test reads UTF-8 output with the locale default.
- 09: The frozen intent run has 8 human-contact requests classified as policy, 7 refund requests as order status, and 6 order requests as fixed replies (`eval/reports/intent.md`). Source labels can mix general rules with individual actions. Review these examples separately before changing mappings or prompts; this held-out run was not tuned.
- 09: Product intent examples use retrieval dev questions; return examples were drafted by the same provider used for classification. Exact duplicates, prompt examples and previously used Bitext utterances are excluded, but near-paraphrases can cross the reserved partition. Source-balanced sampling differs from live traffic. These measurements do not establish multi-turn rewriting, task success, or refusal safety.
- 09: Caller-assigned thread ids must be customer-scoped. Graph authentication and customer/thread ownership enforcement are not present yet. SQLite graph dependencies must stay open during use and be closed afterward. Credentials, selected question text and full predictions remain local.
- 08: All 300 evaluation questions remain unreviewed. Two reranked dev misses recover only part of combined questions; repeated SuperCoins chunks crowd out the other required section. `make eval-failures` exposes their questions, gold sections and headings locally. Only one failure pattern was observed; no extra patterns were invented. Test settings and labels were not tuned.
- 08: The heading-prefix ablation lowers hybrid test Recall@5 to 0.9875. Disabling model-number normalisation leaves measured quality unchanged on this draft set (`eval/reports/retrieval.md`); it has no demonstrated quality gain here.
- 08: Real measurements used CPU embeddings, MPS reranking and compressed SSH forwarding. Separate fingerprinted experiment indexes preserve the demo index. Verified local chunk text avoids remote full-text transfer timeouts; warm-process timings exclude initial snapshot loading. Long manuals are truncated by the configured reranker input limit. MRR uses the same top-five cutoff for every mode. Models, text and full prediction caches stay local; committed CSVs contain ids and metrics only.
- 08: Generated retrieval CSVs use Git LF normalization. The pre-commit Ruff pin matches the existing lockfile, preventing conflicting lint rules between commit hooks and `make check`.
- 07: The task's W40 example is absent from the indexed catalog. Its live query returned charger-related electric-vehicle FAQs, not evidence for W40. Acceptance also used BHD340/10, confirmed from the real index; no synthetic product or eval label was added. Reranking and frozen-set quality comparisons remain in commit 08. The pinned model is cached locally; the existing VPS index remains unchanged.
- 07: `make eval-ingest` now replaces only the measured section of `docs/RETRIEVAL.md`, preserving the handwritten guide. An offline regression test covers repeated regeneration.

- 01/06: The VPS now runs healthy project Milvus, MinIO and etcd containers. Milvus ports bind to loopback and the client connects through SSH forwarding. Existing services remain running. `make up COMPOSE_PYTHON=python3` supports a Docker host without the app environment.
- 02: Data sources changed from the original PRD (see `docs/DATA_NOTES.md`); `docs/PRD.md` → Data updated to match.
- 05: Model-number questions use differing attributes of the 3 look-alike hair dryers; the remaining catalog models lack suitable comparable attributes. No synthetic products added. The 60 questions are attribute combinations, not independent product families (`docs/EVAL_SET.md`).
- 03: Flipkart and Philips text is "unclear"; all mixed `data/processed/` output is gitignored. Reviewers rebuild it locally.
- 03: Empty source questions/answers leave 3 FAQ rows uncovered; raw rows and labels were not edited (`eval/reports/docs_build.md`).
- 03: No fast model was configured for this build; unmatched topic groups use cached `other` decisions. Clear the topic cache to reclassify with a configured model.
- 03/06: Source scopes, conflicting store policies and off-topic categories remain explicit. PDF layout is lossy. Product sections remain whole; bounded encoder windows retain their text without silent truncation. Window pooling quality remains unmeasured.
- 04: Local database `data/orders.sqlite` is gitignored. `make data-orders` resets all mock facts and pending requests; `make eval-orders` audits without changing that database (`docs/ORDERS.md`).
- 04: Product metadata comes from the local catalog when present; prices are synthetic. A missing catalog uses built-in demo products; the catalog hash records which input was used.
- 04: The service expects a trusted customer id. Authentication, policy eligibility and retry idempotency belong to later commits; refund creation only records pending human review.
- 05: All generated eval/review text stays local due mixed-source licenses. Review `eval/sets/review.csv`; only explicit human ok decisions may change review flags. The agent marked no actual questions reviewed.
- 05: No external LLM was configured; authored templates draft cross-document/absent-topic questions. Optional fast-model question drafting is cached. Colloquial questions use real Bitext prefixes with explicit FAQ context.
- 05: Lexical support and absent-key-phrase checks cannot prove meaning or absence. Human review is still required before treating this draft set as a trusted benchmark.
- 01/09: Config `gate.good_evidence_min` remains a placeholder for commit 11. `intent.min_confidence` now only flags uncertain knowledge/after-sales routing; it remains uncalibrated.
- 06: The pinned MinIO source image now builds successfully on the VPS. Compose passes the server subcommand to the image entrypoint without duplicating the executable. A regression test failed before this fix. Go build/module caches are removed inside the build step to reduce retained disk use.
- 06: The pinned BGE-M3 cache is complete and SHA-256 verified on the client. `make ingest` ran offline with the real model and stored 206 rows in the project Milvus collection. `make eval-ingest` records model revision, runtime, timings and corpus hashes. Retrieval and answer quality remain unmeasured; those require the later frozen-set experiments.
