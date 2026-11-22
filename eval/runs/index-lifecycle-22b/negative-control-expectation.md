Written 2026-11-21T12:50:31Z, before any 22b release-check output was seen.

Negative control: the 22a release check on support_chunks_eval_no_heading (chunks embedded
without the heading prefix) against the live run of the step-3 build.

Expectation: release, with no significant paired change. Reason: eval/reports/retrieval.md
shows hybrid_heading_off Recall@5 0.9333 against hybrid 0.9583 on test (dev: 0.9542 against
0.9667), before reranking. The release check measures after reranking, which sees the same
chunk text in both collections. A gap that small gives McNemar too few discordant pairs.
So this control most likely shows the limit of the check's power, not a refusal.
The no-answer rule (zero gate passes) applies either way and could still refuse it.
