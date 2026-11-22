# Claim grounding

## Claim evaluation (25a)

The evaluation reads saved knowledge answers, including the released parts of partial
answers. It keeps the observed part index, question and numbered citation texts.
Whole-question records use the original item question. Multipart records use the
planned part question. The question supplies context only. Evidence comes solely
from the cited text. The splitter keeps abbreviations intact and joins short
fragments to a neighbour in the same paragraph. Fixed notices, handoff text and
phrases listed in `grounding.generic_phrases` are excluded.
Each claim has access to the chunks cited by its paragraph. The extraction uses the
saved citation order and checks the saved section identifiers, so it can recover the
numbered chunks without performing retrieval.

**Do not label the current registered `claims_v1`.** It is a test-only tooling draft.
25b will rebuild it from the saved 24b dev and test runs before human review.
The label and scoring commands require the rebuilt schema with question context.

`claims_v1_sources.json` records paths and hashes for the saved inputs and the
unlabelled set. The builder accepts both standard run directories and legacy E2E JSONL.
To build the full 25b set, supply separate dev and test runs via repeated `--run` flags
and leave `--split` at its default of `all`. Use an explicit higher `--version` when
replacing a registered set. Sampling is seeded, caps real claims per source item, and
fails when a split falls short of its configured quotas.

`make eval-claims-label` exports a fresh blind CSV with empty `label` and `note` fields.
It refuses to overwrite an existing review file. When all real claims have human
labels, run `make eval-claims-label CLAIMS_LABEL_ARGS="--import --version vN"` with the
next registry version. The CSV shows the question, claim and cited text. Import
requires the original IDs, question, claim text, split and sources. The
dataset, provenance and review CSV stay local.

Synthetic negatives change a number, duration, amount or model, or replace a sentence
with one from a different document. Each keeps its original question and cited
sources. Foreign sentences must be factual prose with at least six words and
sentence-final punctuation. A text heuristic excludes links, navigation lines and
heading fragments. The builder uses lexical overlap to find claims that look
supported. Uncited sentences are capped at one third of each split's synthetic
sample. The builder prints every perturbation count and reports duration or amount
shortfalls below five per split. The synthetic group alone supplies its unsupported class by
construction at scoring time. Its label fields remain null and it stays out of the
review CSV. Report its metrics separately from human-labelled claims.

`make eval-claims CLAIMS_EVAL_ARGS="--predictions <local-json> --report <report.md>"`
scores a saved verifier run against the registered dataset hash. The JSON object has
`git_sha`, `config_hash`, `dataset_sha256`, `models`, `date`, `split`, and a
`predictions` list with claim `id` and `verdict`. It reports precision, recall and F1
for unsupported claims by split and group, with Wilson intervals and the configured
recall target. Synthetic rows also report counts and scores per perturbation kind. Partial verdicts count as unsupported. No live verifier runs in 25a.

Saved E2E records can carry an optional claim-verdict list. The run-level support rate
counts supported claims over all recorded claims. The unsupported and removal metrics
use answers with claim verdicts, including checked candidates that ultimately hand
off. Low-grounding handoff rate uses records with grounding instrumentation. Existing
records still load and omit the new metrics when no assessment was recorded. For
before/after hallucination measurement, 25b will reuse the judge and blinded human
confirmation on final answers. That measurement is distinct from verifier verdicts.

## Runtime verification (25)

After the evidence gate and citation coverage checks, the knowledge route prepares
model-written drafts. The `ground` node verifies them before `output_guard` can
publish any text. This applies to whole and multipart knowledge answers. Refund
reasons combine policy with order facts, and their existing citation and return
window checks still govern that route.

The runtime uses the same sentence splitter and `grounding.generic_phrases` list
as the evaluation. Fixed notices and handoff text are outside the check. Generic
phrases may accompany a verified answer. A paragraph needs a supported substantive
claim to be released.

Each claim gets the original customer question or the planned part question for
context. Its evidence consists of the numbered chunks cited by its paragraph. A
claim receives neither sibling sources nor additional retrieval. Exact checks
first compare numbers, durations, amounts, percentages, and model identifiers
against that evidence. They normalize case, punctuation, and equivalent literal
formats such as “30-day” and “30 days.” They do not infer conversions or parse
spelled-out numbers.

Claims that pass the literal checks go into one structured call using the configured
verifier role, which defaults to `fast`. Each claim needs an explicit verdict.
A supported verdict must give a verbatim quote from one of that claim's cited chunks.
Code checks claim IDs and quote membership. This reuses the existing model stack
and avoids a second model download. Quote membership proves provenance. Semantic
support still depends on the verifier and needs live calibration.

Partial and unsupported verdicts remove the claim. Losing the first substantive
claim or all substantive content fails that part. With partial answers enabled,
supported sibling parts can still be released, and failed parts keep their
`low_grounding` reason. A whole grounding handoff carries `low_grounding`. An
unavailable dependency gives `dependency_unavailable`. Missing, duplicate or invalid
verdicts fail closed. Retained paragraphs keep their verified coverage citations.
The reply rebuilds its citation list from those paragraphs.

The graph records assessed claims, their verdicts and removals. The trace records
verdict summaries without claim text. Claims skipped after an exact failure of the
main claim are unassessed. A verifier error has no trusted verdicts. The existing
acceptance rule continues to measure release.

`grounding.enabled` defaults to true. Turning it off restores the previous route,
answer and citation behavior. The full E2E config hash includes grounding settings.
`grounding.split_compound` defaults to false. When enabled, a separate structured
call may divide a compound sentence into exact ordered excerpts. Joined excerpts
must reproduce the original claim. The exact checks run on the resulting pieces
before the verdict call. Compound splitting will be calibrated on dev in 25b.

The API emits customer-visible tokens after the output guard. Grounding therefore
adds work before the first visible answer token. 25b will measure the latency and
cost. Provider callback latency measures internal model output and does not capture
the time a customer waits for the checked reply.

25b will also rebuild and label the claim set, compare verifier results separately
on human-labelled and synthetic claims, and use the existing judge and human
review workflow for final-answer hallucination. No live measurements were taken in 25.
