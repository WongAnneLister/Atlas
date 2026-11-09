# PRD — English E-commerce After-sales Support Agent

(English working copy for coding agents. The Chinese source of truth is the Claude Doc PRD.)

## Goal
Rebuild an e-commerce after-sales AI support agent on public English data and ship, in four weeks,
a public GitHub repo with an English README, a 300-question eval set, and a 2-minute demo video.

Success means:
1. Public repo + English README + 2-minute demo video.
2. 300-question eval set; every design decision has a before/after number.
3. Safety first: 0% false-accept on out-of-scope (no-answer) questions.

**Non-goals:** production deployment, multi-tenancy, real payments, a polished frontend, fine-tuning.

## Users
- **Customer** — wants fast, correct answers. System answers with citations, or hands off when unsure.
- **Human agent** — takes over what AI cannot answer. Handoff carries the conversation + retrieval snapshot.
- **Interviewer (real audience)** — reads README, demo, code. README explains trade-offs; numbers are reproducible.

## Typical questions
| Type | Example | Expected behaviour |
|---|---|---|
| Policy | How long do I have to return an item? | Retrieve policy, answer with citation |
| Model number | Does the W40 come with a charger? | Exact model match; never confuse similar models |
| Colloquial | wanna send my stuff back lol | Understand, treat like the formal question |
| Cross-doc | If I return an item bought with a coupon, do I get the coupon back, and who pays shipping? | Retrieve both places, answer each part |
| Out of scope | Can I pay with gold bars? | Weak evidence → handoff, no made-up answer |
| Refund | I want a refund for my last order. | Get order → read policy → decide |

## Scope
| Feature | Priority |
|---|---|
| Intent routing (9 intents → 5 paths) in LangGraph, key steps fixed in code | P0 |
| Hybrid retrieval (dense + BM25) + RRF + rerank | P0 |
| Evidence gate (4 signals, threshold → handoff) | P0 |
| Cited answers | P0 |
| Refund sub-flow + mock order API | P0 |
| SSE streaming | P0 |
| Eval scripts (300 questions, one command) | P0 |
| Simple chat page (for the demo video) | P0 |
| Langfuse tracing, tags per intent | P1 |
| Three-layer memory | P1 |
| Query decomposition for cross-doc questions | P1 |
| Per-intent thresholds, partial answers | P1 |
| Adversarial set (prompt injection, refund fraud) | P1 |
| MCP tools, caching, multilingual | P2 (not doing) |

## Data
| Dataset | Use | Note |
|---|---|---|
| `NebulaByte/E-Commerce_FAQs` | Main knowledge base: FAQ (659 Flipkart help-centre Q&As, 34 categories) | Off-topic categories (EV, insurance, travel) serve as distractors and no-answer seeds |
| `InfiniFlow/Ecommerce-Customer-Service-Workflow` | Product info: 6 Philips leaflets and user manuals (PDF) | Model codes → model-number questions; only 6 products |
| `MakTek/Customer_support_faqs_dataset` | Extra knowledge: 200 FAQs (~89 unique) | Synthetic, generic |
| `bitext/Bitext-customer-support-llm-chatbot-training-dataset` | Intent + colloquial phrasing: 27 intents, ~27k utterances | Map 27 intents → our 9 |

The original main knowledge base, `qgyd2021/e_commerce_customer_service`, was removed from the Hub.
It was replaced in commit 02. Pinned revisions are in `configs/default.yaml`, findings in
`docs/DATA_NOTES.md`, licenses in `docs/LICENSES.md`. The Flipkart and Philips text is
third-party, so it is marked "unclear" and only download scripts are published.

Gaps we fill ourselves:
1. **Policy documents** — merge related FAQs into long docs (Returns, Shipping, Payments, Membership) so chunking and cross-doc retrieval are actually tested.
2. **Mock orders** — a few hundred generated orders in a local DB.
3. **No-answer and cross-doc questions** — written by us.
4. **Licenses** — check each dataset before use and before publishing.

## System design
Every message: rewrite → classify intent → one of 5 fixed paths. Knowledge answers only after the evidence gate passes.

| Component | Approach |
|---|---|
| Query rewrite | Resolve references from recent turns; leave complete questions unchanged |
| Intent classifier | 9 intents, measured on a Bitext held-out set; cheap model |
| Retrieval | BGE-M3 dense + BM25, both in Milvus; RRF (k = 60); rerank, keep top 5 |
| Evidence gate | 4 signals (top rerank score — largest weight, count of good evidence, top-1/top-2 gap, key-clause hit); threshold from a sweep |
| Refund flow | Mock order API; if no order id, pause and let user pick; policy retrieval fixed in the flow |
| Output | SSE streaming; answers carry source ids |
| Memory (P1) | Recent turns kept whole, older compressed, oldest summarised; order ids and user's own words always kept |
| Observability (P1) | Langfuse traces every step; cost per intent |

## Evaluation
Build the eval set **before** the retrieval code. Re-run all 300 after every change and compare to the previous run.

5 groups × 60: basic policy (from FAQ), model number (similar products), colloquial (Bitext phrasings over FAQ questions),
cross-doc (hand-written, 2–3 sections each), no-answer (hand-written). Each item labels the gold section(s) and answer points;
a validator checks sections exist and answer points appear in the source text.

Each group is split 30 dev / 30 test. Tune on dev, report on test (and on all 300 for reference).

| Metric | Measures | On |
|---|---|---|
| Recall@5 | gold section in top 5 | 240 answerable |
| MRR | how high the gold section ranks | 240 answerable |
| False-accept | answered when it should hand off | 60 no-answer |
| False-reject | handed off when it could answer | 240 answerable |
| Hallucination | made-up facts (LLM judge flags, human confirms) | all 300 |
| Intent accuracy | | Bitext held-out |
| Latency P50/P95 | first token and full answer | all 300 |
| Cost per conversation | tokens and $, per intent | all 300 |

Required experiments: (1) dense vs BM25 vs hybrid vs hybrid+rerank; (2) threshold sweep 0.05→0.95, plot false-accept and false-reject, pick the lowest threshold with 0 false-accept on dev; (3) do not reuse any threshold from previous projects.

## Success criteria
| Metric | Target | Type |
|---|---|---|
| No-answer false-accept | 0% | Hard gate — no release without it |
| Recall@5 | ≥ 95% | Initial target |
| Hallucination (human-confirmed) | ≤ 1% | Initial target |
| Intent accuracy | ≥ 90% | Initial target |
| False-reject, latency P95 | set after baseline | TBD |

Deliverables: public repo runnable with one command; English README (architecture, results, trade-offs, data sources);
eval reports (4 retrieval configs, threshold sweep); 2-minute video (one normal answer, one refund, one refusal).

## Milestones
- **Week 1 — data:** download + license check, merge FAQs into policy docs, generate mock orders. Gate: docs and mock data ready.
- **Week 2 — retrieval:** eval set first, then dense + BM25 + RRF, then rerank; test 4 configs. Gate: 4 configs measured.
- **Week 3 — flow:** LangGraph routing, refund flow + evidence gate, threshold sweep. Gate: no-answer false-accept = 0%.
- **Week 4 — delivery:** Langfuse, English README, demo video. Gate: repo public + video.
- P1 features after week 4.

## Risks
FAQ data too easy (inflated numbers) → long merged docs, at least half hard questions. Synthetic data → Bitext phrasings, limitations in README.
License forbids redistribution → ship download scripts only. Confusion with numbers from other projects → report only this project's numbers.
Time → P0 only. API cost → cheap dev model, cache retrieval results.

## Phase 2 — production grade (after v1 ships)

v1 (weeks 1–4) is shipped and used for job applications first. Phase 2 (about weeks 5–12) hardens it in the author's
focus areas: **RAG, agent context management, memory, evals**, plus the platform work they need.
"Production grade" here means: durable state, fail-closed safety, versioned data and indexes, measured context use,
evals that gate releases with confidence intervals, and a load-tested public deployment. It does **not** mean real customers.

| Track | Commits | Outcome |
|---|---|---|
| Eval platform | 17, 20, 27, 32 | Versioned datasets, bootstrap CIs, judge calibration, CI release gate, red-team suite, multi-turn simulator + trajectory metrics, online feedback and drift |
| Platform & reliability | 18, 19, 21 | Postgres + Redis, durable checkpoints, timeouts/retries/fallback, idempotency, guardrails, auth, rate limits |
| RAG | 22–26 | Incremental ingestion with versioned index + alias switch, policy versions by date, query planning for multi-part questions, claim-level grounding, safe caching |
| Context & memory | 28, 29, 35, 30 | Cache-aware ContextBuilder (stability layers, per-node budgets, provider cache adapter), chunked compaction + pinned facts, a 4-arm prefix-cache A/B (sliding / rolling / chunked / no-cache) with optional vLLM KV benchmark, governed long-term customer memory |
| Human loop | 31 | Handoff queue + agent console; resolved handoffs feed new eval items and doc gaps |
| Ops | 33–34 | Load test + SLOs, public deployment with cost cap, README v2 |

Phase-2 success criteria (each set after measuring the v1 baseline; stated in `docs/RESULTS.md`):
no-answer false-accept stays 0% on test and in CI; red-team attack success ≤ budget; cross-doc full-answer rate up vs v1 with non-overlapping CI;
claim-level hallucination down vs v1; multi-turn task success measured on ≥ 50 simulated scenarios; long-term memory: 0 cross-customer leaks;
P95 latency and cost per conversation within the SLO doc.

## Decisions taken for the open questions (defaults, change in config)
- LLM: provider-agnostic via `init_chat_model`; two roles — `fast` (rewrite, intent, judge pre-filter) and `main` (answers).
- Licenses: checked in commit 02, results in `docs/LICENSES.md`.
- Chat UI: one static HTML page served by FastAPI.
- Demo: recorded video; deployment optional later.
