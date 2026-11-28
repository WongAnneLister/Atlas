# Refund decision prompt v4 (12f): decision rule

Written on 2026-11-28 before any v4 run.

## Problem
With the adopted v3, test scenario sim-017 (CUST-TS01, ORD-999993, bought 2026-08-30, 71 days
before the configured today 2026-11-09) failed 3/3 in the 12e reporting run: the model answered
needs_human because the only retrieved policy is valid until 2026-09-01 and today is later.
This cause was found on a test scenario, so the v4 wording is shaped by test; the decision
below uses dev only, and test runs once afterwards for reporting.

## Change
`refund_decide_v4.md` = v3 plus one rule: a source covers orders whose order_date falls
inside its validity dates, even when today is later. Code checks are unchanged.

## Runs
Same code (the v4 commit), same day, real models, official local index `37e01bfb`, clean
orders copy, answer cache off, session limit lifted. Only `refund.decision_version` differs.
1. Dev refund scenarios (9) x 3 repeats, v3 vs v4, scored by `scenarios_v1@v2`.
2. `eval.refund_decision_eval`, all versions, reported only.

## Adoption rule (dev only)
Switch the default to v4 only if all hold:
- v4 has 0 unexpected refunds on the dev refund scenarios;
- v4 task success on them is at least v3's, counted over the 27 chats;
- in the refund decision eval, v4 has 0 wrong final yes.
Otherwise keep v3 and report the result.

If adopted, run once for reporting: the 9 test refund scenarios x 3 with v4 (compared with
the 12e v3 run) and the smoke release gate with red-team smoke.
