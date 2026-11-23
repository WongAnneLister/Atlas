# 32 — Online feedback, sampled review, and drift monitoring

**What**
I added `turn_feedback`, `online_turn_events`, and `sampled_reviews` tables in migration `0006_online_eval`.
I built idempotent `POST /api/feedback`, thumbs buttons in chat, and Langfuse score attachment.
I added stratified near-threshold review sampling, automatic citation checks, and PSI/KS drift monitoring.
I also built a simulated seven-day traffic replay script and documented everything in `docs/ONLINE_EVAL.md`.

**Why**
Offline eval sets only test questions we already wrote down.
Real traffic shifts when new products launch or policies change without doc updates.
Tracking intent PSI, gate KS, handoff spikes, and thumbs-down rates catches shifts early.
Oversampling turns near the gate threshold focuses human reviewers on the riskiest answers.

**Number**
In the simulated seven-day replay, the Day-5 shift triggered 8/8 drift breaches.
Gate KS hit 0.6616, intent PSI hit 0.4969, and `low_evidence` handoffs jumped to 52.5%.
Thumbs-down delta hit 0.2101, and 63 simulated `kb_gap` items surfaced.
Source: eval/reports/drift.md

**Trade-off**
Because there are no live users here, the drift report uses a simulated replay.
I labeled every replay report clearly as simulated rather than pretending it is real traffic.
Drift alerts never change gate thresholds automatically; humans still review and run `make sweep`.
Online writes also fail open so monitoring errors never block a customer reply.

**Likely follow-up question**
Q: Why oversample turns whose gate score is close to the threshold?
A: High-score answers are usually clear hits, and low-score turns already hand off.
Borderline scores just above the threshold are where false accepts hide most often.
Putting half of our review budget there finds bad answers much faster than uniform sampling.
