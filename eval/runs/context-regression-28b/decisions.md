# Context regression fix — decisions (written before any dev ablation result)

Finding (9b7350e vs 25b 07cf8f5, eval_v1 test, paired): false_reject 16/120 -> 24/120
(p=0.021), pass_rate and citation_validity worse; false_accept 0/30 both. Dev: 10 -> 12/120,
not significant. On single-turn eval_v1 the only prompt that changed is the answer node
(shared L0 preamble + task prompt moved to L4 + current date + pinned facts) plus new token
budgets that can hand off with context_overflow (answer, verify).

Arms on dev (code 7f0973a, answer cache off, local Milvus 4aece1a3, workers 3, rerank cache):
- cur:     shipped defaults
- legacy:  context.enabled=false (every node pre-builder layout, no budgets)
- answer:  profiles.answer.legacy_layout=true (only the answer node pre-builder)

Rule (fixed now):
1. Guards: false_accept must stay 0/30; an arm with a significantly worse citation_validity
   or pass_rate than cur on dev is out.
2. If legacy or answer is significantly better than cur on dev false_reject, adopt it;
   between the two, prefer `answer` unless legacy is significantly better than `answer`
   (it keeps the builder, memory and cache layout for every other node).
3. If no arm differs significantly on dev (expected: dev did not show the regression),
   adopt `answer`: the burden of proof is on a prompt change, and the evidence gate and claim
   checks were calibrated on the pre-builder answer prompt. Report this as a tie-break,
   not as a measured improvement.
4. Test is run once for the adopted arm only, compared with 25b and with 9b7350e, and is
   reported whatever it shows. No further change is made from the test result.

## Dev result (22:06, before any test run of a candidate)
cur FR 11/120, legacy 13/120, answer 14/120; FA 0/30 all; no pairwise difference significant
(cur-vs-legacy p=0.73, cur-vs-answer p=0.51, answer-vs-legacy p=1); citation validity n.s.
Rule 3 applies: adopt `answer` (profiles.answer.legacy_layout=true) as a tie-break, not as a
measured gain. Dev point estimates favour cur slightly; reported as such.
