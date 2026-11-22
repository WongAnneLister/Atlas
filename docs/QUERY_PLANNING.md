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

The largest observed problem was the baseline's whole-question routing. The planner
now runs before that decision. These runs provide little evidence that per-part retrieval alone will raise
cross-document acceptance. The coverage case suggests a mechanism to test on
dev questions. Separate retrieval could surface the passage defining SuperCoins,
since the recorded gold hit identifies a section and that section spans
multiple chunks. It could also preserve the supported tracking explanation in
a partial answer. The saved records identify section ranks and the model's
coverage verdict. They cannot establish whether any retrieved chunk already
contained the definition. A paired run on the frozen multipart set will measure
whether planning and targeted handoff help.

## Design decisions

| Decision | Behavior |
|---|---|
| Plan parts once | Gate-approved parts go to the coverage model in plan order. Its reply must return one decision for each of those parts in that order. |
| Preserve question scope | Date and store scope come from the whole rewritten question. Category detection uses the individual part. |
| Check terms | The planner drops parts with key terms absent from both the original user turn and its rewrite. Fewer than two distinct grounded parts use the whole query. |
| Count no-answer false accepts strictly | Any answered part on a wholly unanswerable item counts as a false accept. |
| Fail closed on dependency errors | A failed retrieval or reranker produces a whole-question handoff. Gate and coverage failures can produce a targeted handoff. |
| Preserve acceptance | Ordinary acceptance means a full answer. Partial answers have separate metrics. |
| Measure partial answers separately | The frozen multipart set includes half-answerable questions as well as pairs with both or neither part answerable. |
| Plan before classification | A heuristic decides whether to call the fast planner. An ordinary single question is classified once on the whole rewrite. |
| Route each planned part | The existing classifier runs on each part. Knowledge plus fixed-reply parts can enter multipart retrieval. The fixed-reply parts are handed off as `unsupported_part`. An operational part, an entirely fixed-reply plan, or a classification error falls back to whole-query classification and the regular path. |

## Runtime flow

`input_guard → rewrite → plan → classify` begins each eligible turn. The planner uses
`planning` configuration for its heuristic and part limit. It makes one bounded model attempt
when the heuristic signals a possible split. The trace records `plan` when the model is called.
Heuristic single questions retain the legacy trace. With `planning.enabled: false`, the
graph connects rewrite directly to classification and the same legacy paths.

For a multipart knowledge route, the graph sends each knowledge part to `retrieve_part`. The
`merge` node assigns shared source numbers in plan order. Each part keeps its own ranked
sources and scores. `gate_parts` checks each knowledge part against its own evidence.
The order-tools fallback keeps its original single retrieval. State records the route source
and each planned intent, including those observed before a whole-query fallback.

Only gate-approved parts and their own sources reach the answer prompt. Quote checks constrain
each answer to its assigned sources. If some parts can be answered, the output guard checks
the partial reply before the API streams it. The targeted handoff keeps the failed parts and
their snapshots for a human. With `knowledge.partial_answers: false`, an incomplete question
goes to a human as a whole. Operational paths can use tools or interrupt for an order picker.
Combining their replies with a knowledge answer remains a follow-up.

The embedding and reranking models are shared. They serialize their own inference, while
the graph can overlap the independent retrieval work. A paired live comparison is reserved
for 24b.

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
