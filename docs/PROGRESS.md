# Progress

Agents: update this file in every commit. Keep it short and factual.

## Status

| # | Commit | Status | Key numbers / notes |
|---|---|---|---|
| 01 | Scaffold | done | Skeleton, typed config, LLM factory, Milvus compose, CI, note checker. No metrics yet. |
| 02 | Data download + licenses | done | PRD main KB `qgyd2021/e_commerce_customer_service` is gone from the Hub; replaced by `NebulaByte/E-Commerce_FAQs` + `InfiniFlow` Philips PDFs. Rows (`data/raw/MANIFEST.json`): flipkart_faqs 659, philips_manuals 6 PDFs, maktek_faqs 200 (~89 unique), bitext 26,872 / 27 intents. Licenses (`docs/LICENSES.md`): flipkart + philips **unclear** (third-party text) → scripts only; maktek apache-2.0 and bitext cdla-sharing-1.0 → **yes**. |
| 03 | Policy documents | done | `eval/reports/docs_build.md`: 12 docs, 122 sections, 7 product models; FAQ coverage 856/859 (99.65%). Extractive prose, source-scoped sections, cached topics, strict fact/provenance checks, byte-identical rebuild. Processed text stays local. |
| 04 | Mock orders + OrderService | done | `eval/reports/orders_seed.md`: 50 customers, 300 orders, 749 items, 8 statuses, 14 named edge cases; 900 cross-customer operations blocked. Deterministic transactional reseed; ownership-scoped service; refund requests stay pending_review. |
| 05 | Eval set | todo | |
| 06 | Chunking + ingestion | todo | |
| 07 | Hybrid retrieval + RRF | todo | |
| 08 | Rerank + retrieval eval | todo | |
| 09 | Graph skeleton + intents | todo | |
| 10 | Tool, complaint, fixed paths | todo | |
| 11 | Evidence gate + knowledge path | todo | |
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

## Checkpoints

- **Checkpoint 1 — Week 1 gate passed.** Commits 02, 03 and 04 are done. Policy documents and mock order data can be rebuilt with Makefile targets.

## Known issues / follow-ups

- 01: `docker compose up -d` not verified — the dev machine has the Docker engine but no Compose plugin. The compose file parses; Milvus health is unchecked.
- 02: Data sources changed from the original PRD (see `docs/DATA_NOTES.md`); `docs/PRD.md` → Data updated to match.
- 03: The 6 Philips PDFs yield 7 models, including both monitor models. No synthetic products added; commit 05 must review model-question diversity (`docs/DOCS_BUILD.md`).
- 03: Flipkart and Philips text is "unclear"; all mixed `data/processed/` output is gitignored. Reviewers rebuild it locally.
- 03: Empty source questions/answers leave 3 FAQ rows uncovered; raw rows and labels were not edited (`eval/reports/docs_build.md`).
- 03: No fast model was configured for this build; unmatched topic groups use cached `other` decisions. Clear the topic cache to reclassify with a configured model.
- 03: Source scopes, conflicting store policies and off-topic categories remain explicit. PDF layout is lossy; retrieval must respect scope and chunk manuals in commit 06.
- 04: Local database `data/orders.sqlite` is gitignored. `make data-orders` resets all mock facts and pending requests; `make eval-orders` audits without changing that database (`docs/ORDERS.md`).
- 04: Product metadata comes from the local catalog when present; prices are synthetic. A missing catalog uses built-in demo products; the catalog hash records which input was used.
- 04: The service expects a trusted customer id. Authentication, policy eligibility and retry idempotency belong to later commits; refund creation only records pending human review.
- 01: Config `gate.good_evidence_min` and `intent.min_confidence` are placeholders to revisit in commits 11 and 09.
