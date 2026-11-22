# Query planning

## Cross-document baseline

The [offline failure report](../eval/reports/cross_doc_failures.md) replays the
saved November 17 full test run and the November 21 smoke runs before and after
the guardrail change. The smoke runs reuse test questions, so their results
describe each run separately.

- The full test run accepted 23 of 30 cross-document items. All 24 items that
  reached knowledge retrieval had both gold sections in the top five. Six of the
  seven rejections went to fixed replies or the after-sales path before reaching
  knowledge retrieval. The remaining rejection reached retrieval through the
  tool fallback and passed the gate. The coverage model marked the SuperCoins
  definition unsupported even though the relevant section appeared in the results.
- The smoke runs accepted 8 of 10 and 9 of 10 cross-document items. Every item
  that reached knowledge retrieval had both gold sections in the top five. Both
  runs sent the same returns-and-shipping question to the after-sales path and
  handed it off with `order_not_found`. The earlier smoke run also recorded an
  answer-model dependency failure.
- Every recorded gate passed across the three runs. The saved answer outcomes
  show zero invalid quotes or quote sources.

The largest observed problem is routing, which happens before the proposed
planner. These runs provide little evidence that per-part retrieval will raise
cross-document acceptance. The coverage case suggests a mechanism to test on
dev questions. Separate retrieval could surface the passage defining SuperCoins,
since the recorded gold hit identifies a section and that section spans
multiple chunks. It could also preserve the supported tracking explanation in
a partial answer. The saved records identify section ranks and the model's
coverage verdict. They cannot establish whether any retrieved chunk already
contained the definition. A paired run on the frozen multipart set will measure
whether planning and targeted handoff help.

## Design decisions

| Decision | Status in 24a |
|---|---|
| Use the planner's ordered list for the coverage response. The answer model returns one coverage part per planned part sent to it, in the same order. | Planned for commit 24. |
| Apply the date and store scope of the whole rewritten question to every part. Detect the product category separately for each part. | Planned for commit 24. |
| Require all declared key terms of each part to appear in either the original or rewritten question. Drop and log an invalid part, and use single-question retrieval if none survive. | Planned for commit 24. |
| Count a false accept when any part of a wholly unanswerable question receives an answer. | Implemented in the evaluation metrics. |
| Send the whole question to a human when any part's retrieval or reranker has a dependency error. Gate and coverage outcomes can lead to targeted handoff. | Planned for commit 24. |
| Keep ordinary acceptance reserved for full answers and measure partial answers separately. | Implemented in the evaluation metrics. |
| Freeze a multipart set with both-answerable, half-answerable and wholly unanswerable questions. Keep both source questions in the same split and record their IDs. | Implemented in the evaluation set builder. |

The proposed knowledge flow plans the rewritten question, retrieves and gates
each part, then checks coverage and citations on the parts that cleared the
gate. The graph hands off unsupported parts. A live comparison is reserved for
24b, after the planning code lands.

## Running and reviewing the benchmark

`make eval-multipart-build` recreates the registered local-only set.
`make eval-multipart MULTIPART_ARGS="--split test"` is the live collector for 24b.
It uses the full graph, an in-memory checkpoint, and a scratch copy of the SQLite order database.
Use `--run-dir <run>` to render existing results. Add `--sample-output <run>/review.csv` to
export partial answers for human review. The optional `--judge` calls the model on that saved run.
Keep the review CSV and per-item rows local.

The saved baseline has one retrieval for the whole question. Its part recall checks whether
that list contains all gold sections. New records can describe each part's gate,
retrieved sections, handoff and citations. Full-answer rate requires all gold sections
to be cited in a fully answered response. The deterministic multipart checks use
case- and punctuation-normalized part text for attribution. A paraphrase may require the
judge or a human to verify the match. The judge assesses the evidence supplied with the run.
