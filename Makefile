# Every entry point has a target here (AGENTS.md §4).
# Targets for code that does not exist yet print a notice and exit 0.

UV ?= uv
RUN := $(UV) run
MODE ?= hybrid
CUSTOMER ?= CUST-0001
SPLIT ?= test
EVAL_RETRIEVAL_ARGS ?=
EVAL_INTENT_ARGS ?=
export Q
# Opt-in speed-ups for eval-e2e, eval-smoke and eval-multipart (docs/EVAL_PLATFORM.md):
# EVAL_WORKERS=4 runs four items at once; EVAL_RERANK_CACHE=1 reuses cached reranker scores.
E2E_SPEED_ARGS = $(if $(EVAL_WORKERS),--workers $(EVAL_WORKERS)) $(if $(EVAL_RERANK_CACHE),--rerank-cache)
COMPOSE_PYTHON ?= $(RUN) python

.PHONY: setup up up-state down migrate data data-download data-licenses data-docs data-validate-docs data-orders \
        eval-docs eval-orders eval-orders-parity \
        eval-build eval-validate eval-review eval-review-import eval-set-report \
        index-plan index-build index-release index-rollback index-status index-adopt index-gc \
        ingest ingest-chunks embedding-cache eval-ingest test-milvus eval-retrieval eval-intent eval-e2e sweep serve \
        lint format typecheck test check notes-check notes minio-image-local search reranker-cache \
        eval-retrieval-index eval-failures eval-intent-build eval-intent-draft gate-analysis chat \
        eval-judge eval-judge-import eval-compare eval-routing eval-coverage eval-coverage-summary \
        eval-holdout-build eval-gate-round3 eval-store-scope eval-store-controls-build eval-store-fr \
        eval-tools-fallback eval-paraphrase-build eval-chunking-ab \
        eval-chunking-e2e eval-safety-fixes eval-order-grounding eval-order-replies eval-model-veto \
        results eval-refund-policy eval-refund-decisions eval-validate-all eval-registry-bump \
        eval-time-sensitive-build eval-time-sensitive eval-time-sensitive-e2e eval-policy-versions-report \
        eval-cross-doc-failures eval-multipart-build eval-multipart eval-query-planning-report \
        eval-claims-build eval-claims-label eval-claims eval-claims-verify eval-claim-grounding-report \
        eval-cache eval-sim-build eval-sim eval-context eval-memory-short eval-memory-long eval-context-ab bench-kv loop-report seed-handoff-demo \
        eval-index-release eval-index-lifecycle eval-rerank-cache eval-import-legacy eval-judge-calibration eval-smoke-build eval-smoke eval-redteam-build eval-redteam chaos eval-gate eval-baseline

define todo
	@echo "$@: not implemented yet (commit $(1))"
endef

setup:
	$(UV) sync --all-extras
	$(RUN) pre-commit install

up:
	$(COMPOSE_PYTHON) scripts/compose.py up -d

up-state:
	$(COMPOSE_PYTHON) scripts/compose.py up -d --wait postgres redis

down:
	$(COMPOSE_PYTHON) scripts/compose.py down

migrate:
	$(RUN) python -m support_agent.db.migrate

minio-image-local:
	$(RUN) python scripts/build_minio.py

data: data-download data-licenses data-docs
	$(MAKE) data-orders

data-download:
	$(RUN) python -m support_agent.data.download

data-licenses:
	$(RUN) python -m support_agent.data.licenses

data-docs:
	$(RUN) python -m support_agent.data.build_docs
	$(RUN) python -m support_agent.data.validate_docs
	$(RUN) python eval/docs_build.py

data-validate-docs:
	$(RUN) python -m support_agent.data.validate_docs

eval-docs:
	$(RUN) python eval/docs_build.py

data-orders:
	$(RUN) python -m support_agent.orders.seed
	@if [ "$${ENV:-local}" = local ]; then $(RUN) python eval/orders_seed.py; fi

eval-orders-parity:
	$(RUN) python -m eval.orders_parity

eval-orders:
	$(RUN) python eval/orders_seed.py

eval-build:
	$(RUN) python -m eval.build_set
	$(RUN) python -m eval.review
	$(RUN) python -m eval.report_set

eval-validate:
	$(RUN) python -m eval.validate_set

eval-review:
	$(RUN) python -m eval.review

eval-review-import:
	$(RUN) python -m eval.review --import-csv "$(REVIEW_CSV)"
	$(RUN) python -m eval.report_set

eval-holdout-build:
	$(RUN) python -m eval.build_holdout --version $(or $(HOLDOUT),v1)

eval-set-report:
	$(RUN) python -m eval.report_set

ingest:
	$(RUN) python -m support_agent.ingest $(INDEX_ARGS)

ingest-chunks:
	$(RUN) python -m support_agent.ingest --chunks-only
	$(RUN) python -m eval.ingestion --preview

embedding-cache:
	$(RUN) python -m support_agent.retrieval.embed

reranker-cache:
	$(RUN) python -m support_agent.retrieval.rerank

eval-retrieval-index:
	$(RUN) python -m eval.retrieval_index

eval-ingest:
	$(RUN) python -m eval.ingestion

test-milvus:
	$(RUN) pytest -m integration tests/test_milvus_integration.py --junitxml=data/processed/milvus_integration.xml

eval-retrieval:
	$(RUN) python -m eval.retrieval_eval --split "$(SPLIT)" $(EVAL_RETRIEVAL_ARGS)

gate-analysis:
	$(RUN) python -m eval.gate_dev_analysis

eval-failures: MODE = hybrid_rerank
eval-failures: SPLIT = dev
eval-failures:
	$(RUN) python -m eval.failures --mode "$(MODE)" --split "$(SPLIT)"

search:
	$(RUN) python scripts/search.py --mode "$(MODE)"

chat:
	$(RUN) python scripts/chat_cli.py --customer "$(CUSTOMER)"

eval-intent:
	$(RUN) python -m eval.intent_eval $(EVAL_INTENT_ARGS)

eval-routing:
	$(RUN) python -m eval.routing_eval $(EVAL_ROUTING_ARGS)

eval-coverage:
	$(RUN) python -m eval.coverage_eval $(EVAL_COVERAGE_ARGS)

eval-coverage-summary:
	$(RUN) python -m eval.coverage_summary $(EVAL_COVERAGE_SUMMARY_ARGS)

eval-intent-build:
	$(RUN) python -m eval.intent_data

eval-intent-draft:
	$(RUN) python -m eval.intent_draft

eval-e2e:
	$(RUN) python -m eval.e2e_eval $(E2E_SPEED_ARGS) $(EVAL_E2E_ARGS)

sweep:
	$(RUN) python -m eval.sweep $(SWEEP_ARGS)

eval-gate-round3:
	$(RUN) python -m eval.gate_round3 $(EVAL_GATE_ROUND3_ARGS)

eval-chunking-ab:
	$(RUN) python -m eval.chunking_ab $(EVAL_CHUNKING_AB_ARGS)

eval-paraphrase-build:
	$(RUN) python -m eval.build_paraphrase_holdout

eval-store-controls-build:
	$(RUN) python -m eval.build_store_controls

eval-tools-fallback:
	$(RUN) python -m eval.tools_fallback_report

eval-chunking-e2e:
	$(RUN) python -m eval.chunking_e2e_report

eval-refund-policy:
	$(RUN) python -m eval.refund_policy_eval $(EVAL_REFUND_POLICY_ARGS)

eval-refund-decisions:
	$(RUN) python -m eval.refund_decision_eval $(EVAL_REFUND_DECISIONS_ARGS)

eval-model-veto:
	$(RUN) python -m eval.model_veto

eval-order-replies:
	$(RUN) python -m eval.order_replies_eval $(ORDER_REPLIES_ARGS)

eval-order-grounding:
	$(RUN) python -m eval.grounding_eval $(ORDER_GROUNDING_ARGS)

eval-safety-fixes:
	$(RUN) python -m eval.safety_fixes_report

eval-store-fr:
	$(RUN) python -m eval.store_fr_report

eval-store-scope:
	$(RUN) python -m eval.store_scope_report

eval-judge:
	$(RUN) python -m eval.judge $(EVAL_JUDGE_ARGS)

eval-judge-import:
	$(RUN) python -m eval.judge --import-csv "$(CONFIRMATIONS)"

eval-compare:
	$(RUN) python -m eval.compare "$(A)" "$(B)" $(EVAL_COMPARE_ARGS)

eval-validate-all:
	$(RUN) python -m eval.registry validate $(EVAL_VALIDATE_ALL_ARGS)

eval-registry-bump:
	$(RUN) python -m eval.registry bump "$(NAME)" --version "$(VERSION)" --note "$(NOTE)"

eval-import-legacy:
	$(RUN) python -m eval.import_legacy $(EVAL_IMPORT_ARGS)

eval-judge-calibration:
	$(RUN) python -m eval.judge_calibration $(EVAL_JUDGE_CALIBRATION_ARGS)

eval-redteam-build:
	$(RUN) python -m eval.redteam_build

eval-redteam: eval-redteam-build
	$(RUN) python -m eval.redteam_eval $(EVAL_REDTEAM_ARGS)

eval-smoke-build:
	$(RUN) python -m eval.smoke

eval-smoke: eval-smoke-build
	$(RUN) python -m eval.e2e_eval --split test --eval-file eval/sets/smoke.jsonl \
		--expect-dataset smoke --fresh --report eval/runs/smoke.md $(E2E_SPEED_ARGS) $(EVAL_SMOKE_ARGS)

chaos: $(if $(CHAOS_RUN),,eval-smoke-build)
	$(RUN) python -m eval.chaos $(if $(CHAOS_RUN),--run-dir "$(CHAOS_RUN)") $(EVAL_CHAOS_ARGS)

eval-gate:
	$(UV) run python -m eval.gate check "$(RUN)" $(EVAL_GATE_ARGS)

eval-baseline:
	$(UV) run python -m eval.gate promote "$(RUN)" $(EVAL_BASELINE_ARGS)

serve:
	$(RUN) python -m support_agent.api

results:
	$(RUN) python scripts/render_results.py --results-doc docs/RESULTS.md

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck:
	$(RUN) mypy

test:
	$(RUN) pytest $(TEST_ARGS)

notes-check:
	$(RUN) python scripts/check_notes.py

notes:
	$(RUN) python scripts/check_notes.py --build

check: lint typecheck test notes-check

eval-index-release:
	$(RUN) python -m eval.index_release $(INDEX_EVAL_ARGS)

# Commit 22b evidence: `vectors <first> <second> --output <path>` or `report` (the default).
eval-index-lifecycle:
	$(RUN) python -m eval.index_lifecycle_report $(or $(LIFECYCLE_ARGS),report)

# Rerank score cache evidence: `measure --live <collection> --candidate <collection>
# --reranker-device <device>` collects three runs; `report` (the default) renders them.
eval-rerank-cache:
	$(RUN) python -m eval.rerank_cache_report $(or $(RERANK_CACHE_ARGS),report)

index-plan index-build index-rollback index-status index-gc:
	$(RUN) python -m eval.index_lifecycle $(@:index-%=%) $(INDEX_ARGS)

index-release:
	$(RUN) python -m eval.index_lifecycle release "$(BUILD)" $(INDEX_ARGS)

index-adopt:
	$(RUN) python -m eval.index_lifecycle adopt "$(COLLECTION)" $(INDEX_ARGS)

eval-time-sensitive-build:
	$(RUN) python -m eval.build_time_sensitive

eval-time-sensitive:
	$(RUN) python -m eval.time_sensitive_eval $(TIME_SENSITIVE_ARGS)

eval-time-sensitive-e2e:
	$(RUN) python -m eval.time_sensitive_e2e $(TIME_SENSITIVE_E2E_ARGS)

eval-policy-versions-report:
	$(RUN) python -m eval.policy_versions_report $(POLICY_VERSIONS_REPORT_ARGS)

eval-cross-doc-failures:
	$(RUN) python -m eval.cross_doc_failures $(CROSS_DOC_FAILURES_ARGS)

eval-multipart-build:
	$(RUN) python -m eval.build_multipart

eval-multipart:
	$(RUN) python -m eval.multipart_eval $(E2E_SPEED_ARGS) $(MULTIPART_ARGS)

eval-query-planning-report:
	$(RUN) python -m eval.query_planning_report $(QUERY_PLANNING_REPORT_ARGS)

eval-claims-build:
	$(RUN) python -m eval.build_claims $(CLAIMS_BUILD_ARGS)

eval-claims-label:
	$(RUN) python -m eval.claim_labels $(CLAIMS_LABEL_ARGS)

eval-claims:
	$(RUN) python -m eval.claims_eval $(CLAIMS_EVAL_ARGS)

eval-claims-verify:
	$(RUN) python -m eval.claims_verify $(CLAIMS_VERIFY_ARGS)

eval-claim-grounding-report:
	$(RUN) python -m eval.claim_grounding_report $(CLAIM_GROUNDING_REPORT_ARGS)

eval-cache:
	$(RUN) python -m eval.cache_eval $(EVAL_CACHE_ARGS)

eval-sim-build:
	$(RUN) python -m eval.sim.build_scenarios $(EVAL_SIM_BUILD_ARGS)

eval-sim:
	$(RUN) python -m eval.sim.run $(EVAL_SIM_ARGS)

eval-context:
	$(RUN) python -m eval.context_eval $(EVAL_CONTEXT_ARGS)

eval-memory-short:
	$(RUN) python -m eval.memory_short_eval $(EVAL_MEMORY_SHORT_ARGS)

eval-memory-long:
	$(RUN) python -m eval.memory_long_eval $(EVAL_MEMORY_LONG_ARGS)

eval-context-ab:
	$(RUN) python -m eval.context_ab $(EVAL_CONTEXT_AB_ARGS)

bench-kv:
	$(RUN) python bench/kv/run_kv_bench.py $(BENCH_KV_ARGS)

loop-report:
	$(RUN) python -m eval.loop_report $(LOOP_REPORT_ARGS)

seed-handoff-demo:
	$(RUN) python scripts/seed_handoff_demo.py
