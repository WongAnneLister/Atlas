# Classifier prompt, round 13e: decision rule

Written on 2026-11-28 before any run of the changed prompt.

## Problem
On the fully reviewed intent holdout (13d, 0.8619) the classifier's main errors were:
permission questions about returns and exchanges sent to return_exchange, reported account
problems sent to policy_question, and refund-tracking requests sent to order_status. The
holdout is a reporting set and is not used to tune; its examples are not copied below.

## Change
Three lines in `classify.md`: (1) asking whether one may return, exchange or replace an item
is policy_question, asking the store to do it is return_exchange; (2) a reported problem with
an account, sign-up or subscription action is chitchat_other unless it asks how something
works; (3) checking or tracking a refund is refund_request, not order_status.

## Runs
1. `eval.routing_eval`, same code, before (`eval/prompts/routing_13e_before.md`) vs after
   (`eval/prompts/routing_13e_after.md`), eval_v1 dev answerable questions plus the authored
   controls, once each. Six agent-drafted controls were added before inference.
2. If kept: dev refund scenarios (9) x 3, the smoke release gate with red-team smoke, and the
   intent holdout once for reporting.

## Adoption rule (routing dev and controls only)
Keep the change only if all hold:
- dev answerable path accuracy drops by at most 1 item, paired;
- every control that passes with the before prompt still passes;
- at least 5 of the 6 new controls pass with the after prompt.
After keeping it, it is reverted if the dev refund scenarios show any unexpected refund or
fall below 25/27, or if the release gate fails. The intent holdout result does not change
the decision.
