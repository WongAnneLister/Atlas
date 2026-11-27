# Refund decision prompt v3 (12d): decision rule

Written on 2026-11-27 before any v3 run on these sets.

## Problem
With `refund.decision_version: v2`, the eligible test scenario sim-017 (CUST-TS01, ORD-999993,
bought 2026-08-30 under the 90-day policy) failed 3/3 in the 12c run: the code check
`outside_window` downgrades a yes when any retrieved return window is exceeded, here the
current 30-day window. v3 counts the window from the date the policy names. It passed the
window holdout 20/20 in `eval/reports/refund_decisions.md`, but that holdout has been seen
(v3 was written after reading v2 errors), so it cannot decide this.

## Runs
Same code (`0bee183`), same day, real models, official local index `37e01bfb`, clean orders
copy, answer cache off, session limit lifted. Only `refund.decision_version` differs.
1. Dev refund scenarios (9: sim-013..015, 019..021, 025..027) x 3 repeats, v2 vs v3.
2. `eval.refund_decision_eval` (named orders and window holdout, all versions), reported only.

## Adoption rule (dev only)
Switch the default to v3 only if all hold on the dev refund scenarios:
- v3 creates no refund request in any chat whose expected outcome is not `refund_created`;
- v3 task success (current rules) is at least v2's, counted over the 27 chats;
- in the refund decision eval, v3 has 0 wrong final yes.
Otherwise keep v2 and report the result.

If adopted, run the 9 test refund scenarios x 3 once with v3 for reporting, and compare
with the 12c after run (v2). Test results do not change the decision.
