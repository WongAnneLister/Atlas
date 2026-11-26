# Long-Term Customer Memory Evaluation (Commit 30)

## Provenance
- Date: `2026-11-26 15:07 UTC`
- Git SHA: `2cc6005` (dirty: False)
- Config hash: `d08c78dba1c439ec084f3d3f14af651d0685d38c2ad8229c95aa6e9a625e30fd`
- Memory config hash: `d47504775454`
- Models: fast=`deepseek-flash`, main=`deepseek-flash`
- Scenarios: `30` two-session scenarios (10 recall, 8 stale_update, 6 leak_canary, 6 deletion)

## Memory OFF vs Memory ON (with 95% Wilson CIs)

| Metric | Memory OFF | Memory ON |
|---|---|---|
| Cross-session fact use (recall) | 1/10 (10.0%, 95% CI [1.8%, 40.4%]) | 1/10 (10.0%, 95% CI [1.8%, 40.4%]) |
| Recall memory loaded into the prompt (diagnostic) | 0/10 (0.0%, 95% CI [0.0%, 27.8%]) | 10/10 (100.0%, 95% CI [72.2%, 100.0%]) |
| Redundant questions in session 2 | 0/10 (0.0%, 95% CI [0.0%, 27.8%]) | 0/10 (0.0%, 95% CI [0.0%, 27.8%]) |
| Stale-memory errors (stale_update) | 0/8 (0.0%, 95% CI [0.0%, 32.4%]) | 0/8 (0.0%, 95% CI [0.0%, 32.4%]) |
| Cross-customer leak rate (canaries) | 0/6 (0.0%, 95% CI [0.0%, 39.0%]) | 0/6 (0.0%, 95% CI [0.0%, 39.0%]) |
| Deletion honoured rate | 6/6 (100.0%, 95% CI [61.0%, 100.0%]) | 6/6 (100.0%, 95% CI [61.0%, 100.0%]) |
| Session 2 latency mean / P50 / P95 (ms) | 10382 / 13165 / 16966 | 10814 / 14680 / 17469 |
| Added latency (ON - OFF mean) | - | +432 ms |
| Storage per customer (active bytes / rows) | 0.0 B / 0.00 | 102.4 B / 1.43 |
| Junk rate (human review) | — | pending human review (`0/43` reviewed; CSV: `eval/reports/memory_long_review.csv`) |

## Safety Checks
- Cross-customer canary leaks: `0/6` (target: `0`).
- Deleted memories resurfaced: `0/6` (target: `0`).
- Long-term memories are injected as hints only (`L1_session` frozen at turn 1, `L4_turn` for mid-turn lookup) and never satisfy the evidence gate or citations.
