# Classifier rule for "cancel and refund" (12h): decision rule

Written on 2026-11-28 before any run of the changed prompt.

## Problem
In the 12g test run of sim-030 (ORD-000012, shipped; expected handoff:policy_requires_human),
two of three requests to "cancel it and get a refund" were classified as order_status. The
tools path cannot cancel, so they handed off with low_evidence instead of reaching the refund
decision. The classifier prompt lists "cancel" under order_status and has no rule for a
request that asks to cancel and to get the money back.

This was found on a test scenario. No intent eval item and no dev refund scenario asks to
cancel and refund, so no set available for deciding can show the gain; the runs below only
guard against harm.

## Change
One line in `classify.md`: a request to cancel an order and get the money back is
refund_request; cancelling without asking for the money back stays order_status.

## Runs
Same day, real models, answer cache off, official local index.
1. Intent eval (`eval.intent_eval`, intent_holdout, 530 items), before (current main) and
   after (the prompt commit), once each; this set is a guard, not tuned on.
2. Dev refund scenarios (9) x 3 after; before is the 12g dev run at `f8a134f`, whose code
   differs only by this prompt line.

## Adoption rule
Keep the new line only if all hold:
- intent accuracy and path accuracy on intent_holdout do not drop by more than 1 item in
  100 (0.01) and no intent loses more than 2 items;
- the dev refund scenarios have 0 unexpected refunds and task success at least the 12g dev
  run's (96.30%, 26/27) minus one chat.
Otherwise revert the line and report.

If kept, run the 9 test refund scenarios x 3 once for reporting, against the 12g test run.

## Amendment (2026-11-28, before any result of the changed prompt)
Run 1 above cannot run: the frozen intent holdout is bound to the classify prompt of
2026-11-10 (`fbbbfd3`), which changed on 2026-11-11, and `docs/ROUTING_ROUND1.md` forbids a
silent rebuild. The first attempt failed on that check (and on a missing raw file) before
producing any result. Run 1 is replaced by the method used for the last classifier change:
`eval.routing_eval` on the eval_v1 dev questions plus the authored controls, before prompt
(`eval/prompts/routing_12h_before.md`, classify.md at `554322e`) vs after
(`eval/prompts/routing_12h_after.md`), same code, once each. Three agent-drafted controls
were added before inference: two cancel-and-refund requests (expected path C) and one
cancel-only request (expected path A).

Amended adoption rule: keep the line only if all hold:
- dev path accuracy drops by at most 1 item, paired;
- every control that passes with the before prompt still passes, and the two new
  cancel-and-refund controls pass with the after prompt;
- the dev refund scenarios condition above.
