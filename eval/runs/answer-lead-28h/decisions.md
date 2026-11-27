# Answer lead-sentence prompt (28h): decision rule

Written on 2026-11-27 before any run of the changed prompt.

## Problem
On sim-049 turn 14 (memory_short `both` arm, released split build `369f54d6`), the warranty
part's answer opened with a summary sentence ("Each product has its own warranty terms.").
The verifier judged it unsupported or partial in 3/3 instrumented replays. The grounding
step treats a part's first claim as its main claim, so the part was dropped although its
second, substantive sentence was verified, and the turn handed off with `low_grounding`.
Saved eval_v1 test rows show the same pattern once ("Update your email ID:" as a lead).

## Change
Both answer prompts (`answer.md`, `answer_parts.md`) gain a shared instruction: begin each
answer with the sentence that answers the question with its key fact; no summary, heading,
or general opening sentence. Grounding rules are unchanged.

## Runs
Same day, same models, answer cache off, local Milvus copy with the default live alias
(`support_chunks_live`, build `4aece1a3`), scratch orders DB, `--workers 3` and the rerank
cache. Before arm: `dfe8c4f`. After arm: the prompt commit.
1. eval_v1 dev (150 items), paired with `make eval-compare`.
2. multipart dev (50 items), paired.
3. sim-049 turn 14 replay on the split build `369f54d6` (scratch alias `atlas_c28d_live`),
   5 repeats, after arm only; the before arm is the 28f replay (`low_grounding` 5/5 with the
   fit on) plus the 3/3 instrumented replay.

## Adoption rule (dev only)
Adopt the prompt only if all hold:
- eval_v1 dev no-answer false accepts stay 0/30 and multipart dev no-answer false accepts
  stay 0;
- no significant worsening (paired test, alpha 0.05) of eval_v1 dev false_reject, pass_rate
  or citation_validity, or of multipart dev full_answer_rate or answered_part_correct;
- and either a significant improvement on one of those metrics, or, if every metric ties,
  the sim-049 replay answers the warranty part in at least 3/5 runs.
Otherwise revert the prompt and report the result.

If adopted, run once for reporting: eval_v1 test before and after, and the smoke release
gate with red-team smoke on the after arm. Test results do not change the decision.
