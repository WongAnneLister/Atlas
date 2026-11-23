# Online Evaluation & Drift Monitoring (`docs/ONLINE_EVAL.md`)

Offline evals (Commits 17–27) measure known regression sets, while online evaluation tracks how Atlas behaves on live traffic through three layers: explicit customer feedback, stratified human review, and statistical drift monitoring.

## 1. Online Signals

1. **Explicit customer feedback (`POST /api/feedback`)**:
   - Thumbs up/down + optional reason on every AI answer in the chat page.
   - Idempotent per `message_id` (`turn_feedback` table, migration `0006_online_eval.py`).
   - Increments Prometheus `atlas_feedback_total{rating}` and attaches a `user_feedback` score to the Langfuse trace (no-op when tracing is disabled).
2. **Cheap automatic online checks (`src/support_agent/observability/online_checks.py`)**:
   - Citation validity (`check_citation_validity`), claim-grounding removals, and guardrail flags recorded per turn into `online_turn_events` and `atlas_online_citation_valid_total`.
   - Writes are non-blocking: failures are logged and never fail or delay a customer reply.
   - All stored question/answer previews are PII-redacted via `redact_pii()`. No raw customer text ever enters Prometheus labels.
3. **Stratified sampled review (`src/support_agent/observability/sampler.py`)**:
   - Nightly job samples `sample_size` (default 20) answered turns into `sampled_reviews`, stratified across intents and oversampling gate scores within `±near_threshold_band` (`±0.10`) of `gate.threshold` (weight `0.50`).
   - Reviewers with the agent role inspect items via `/api/agent/reviews` and label them with the 4-way rubric: `correct`, `partially_correct`, `wrong`, `should_have_handed_off`. Non-`correct` items export as unreviewed eval candidates (`reviewed: false`) entering the same review workflow as Commit 31.
4. **Drift monitoring (`src/support_agent/observability/drift.py`, `make drift-report`)**:
   - Compares the current window against a reference window and exports every signal to Prometheus gauge `atlas_drift_metric{metric=...}` and `eval/reports/drift.md`.

## 2. Signal-to-Action Matrix

| Signal | Default threshold | Owner | Triggered action |
|---|---:|---|---|
| `intent_psi` | `>= 0.20` | Support Ops / ML | Inspect new customer topics; check classifier routing |
| `gate_score_ks` / `gate_score_psi` | `>= 0.15` / `>= 0.20` | Retrieval / KB | Check for missing policy docs or index staleness |
| `handoff_rate_delta` | `>= 0.10` | Support Ops | Break down by reason; inspect `low_evidence` spikes in `/console` |
| `rewrite_skip_delta` | `>= 0.15` | ML / Agent | Check multi-turn conversation length or rewrite errors |
| `tokens_per_turn_ratio` | `>= 0.25` | Platform / Cost | Inspect `atlas_context_tokens_total` and compaction triggers |
| `cost_per_conv_ratio` | `>= 0.25` | Platform / Cost | Check prefix-cache hit ratio and fallback model rate |
| `thumbs_down_delta` | `>= 0.10` | Support Ops / ML | Prioritise thumbs-down turns in the nightly sampled review queue |

## 3. Limitations & Policy

- **No automatic threshold changes**: Drift alerts notify humans; gate thresholds still change only through `make sweep` on `dev` + CI release gate (`make eval-gate`).
- **Simulated demo traffic**: Because this repo has no live production customers, `make replay-traffic` (`scripts/replay_traffic.py`) replays a deterministic 7-day simulated week with a deliberate Day-5 surge on a missing topic (international warranty transfer / gift cards). Reports generated from it are explicitly tagged `SIMULATED WEEK REPLAY`.
