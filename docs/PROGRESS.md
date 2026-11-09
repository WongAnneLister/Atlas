# Progress

Agents: update this file in every commit. Keep it short and factual.

## Status

| # | Commit | Status | Key numbers / notes |
|---|---|---|---|
| 01 | Scaffold | done | Skeleton, typed config, LLM factory, Milvus compose, CI, note checker. No metrics yet. |
| 02 | Data download + licenses | done | PRD main KB `qgyd2021/e_commerce_customer_service` is gone from the Hub; replaced by `NebulaByte/E-Commerce_FAQs` + `InfiniFlow` Philips PDFs. Rows (`data/raw/MANIFEST.json`): flipkart_faqs 659, philips_manuals 6 PDFs, maktek_faqs 200 (~89 unique), bitext 26,872 / 27 intents. Licenses (`docs/LICENSES.md`): flipkart + philips **unclear** (third-party text) → scripts only; maktek apache-2.0 and bitext cdla-sharing-1.0 → **yes**. |
| 03 | Policy documents | todo | |
| 04 | Mock orders + OrderService | todo | |
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

_none yet_

## Known issues / follow-ups

- 01: `docker compose up -d` not verified — the dev machine has the Docker engine but no Compose plugin. The compose file parses; Milvus health is unchecked.
- 02: Data sources changed from the original PRD (see `docs/DATA_NOTES.md`); `docs/PRD.md` → Data updated to match.
- 02: Only 6 products (Philips PDFs). Commit 03/05 must decide if that covers 60 `model_number` questions or needs a synthetic catalog.
- 02: Flipkart and Philips text is "unclear" → commit 03 must not commit processed docs built from them.
- 01: Config `gate.good_evidence_min` and `intent.min_confidence` are placeholders to revisit in commits 11 and 09.
