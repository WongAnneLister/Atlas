# Claim grounding

## Claim evaluation (25a)

The evaluation reads saved knowledge answers, including the released parts of partial
answers. It splits those paragraphs into sentences and keeps the observed part index
and the original numbered citation texts. Fixed notices and handoff text are excluded.
Each claim has access to the chunks cited by its paragraph. The extraction uses the
saved citation order and checks the saved section identifiers, so it can recover the
numbered chunks without performing retrieval.

The current local-only registry entry is an unreviewed test draft. Rebuild it from
the same existing inputs with:

    make eval-claims-build CLAIMS_BUILD_ARGS="--split test --run eval/runs/baseline-001-e2e-test.jsonl --run eval/runs/e2e-test-c15.jsonl"

`claims_v1_sources.json` records paths and hashes for the saved inputs and the
unlabelled set. The builder accepts both standard run directories and legacy E2E JSONL.
To build the full 25b set, supply separate dev and test runs via repeated `--run` flags
and leave `--split` at its default of `all`. Use an explicit higher `--version` when
replacing a registered set. Sampling is seeded, caps real claims per source item, and
fails when a split falls short of its configured quotas.

`make eval-claims-label` exports a fresh blind CSV with empty `label` and `note` fields.
It refuses to overwrite an existing review file. When all real claims have human
labels, run `make eval-claims-label CLAIMS_LABEL_ARGS="--import --version vN"` with the
next registry version. Import requires the original IDs, text, split and sources. The
dataset, provenance and review CSV stay local.

Synthetic negatives change a number, duration, amount or model, or replace a sentence
with one from a different document. Each keeps its original cited sources. The
builder uses lexical overlap to select source claims that look supported. This is a
sampling heuristic. The synthetic group alone supplies its unsupported class by
construction at scoring time. Its label fields remain null and it stays out of the
review CSV. Report its metrics separately from human-labelled claims.

`make eval-claims CLAIMS_EVAL_ARGS="--predictions <local-json> --report <report.md>"`
scores a saved verifier run against the registered dataset hash. The JSON object has
`git_sha`, `config_hash`, `dataset_sha256`, `models`, `date`, `split`, and a
`predictions` list with claim `id` and `verdict`. It reports precision, recall and F1
for unsupported claims by split and group, with Wilson intervals and the configured
recall target. Partial verdicts count as unsupported. No live verifier runs in 25a.

Saved E2E records can carry an optional claim-verdict list. The run-level support rate
counts supported claims over all recorded claims. The unsupported and removal metrics
use answers with claim verdicts, including checked candidates that ultimately hand
off. Low-grounding handoff rate uses records with grounding instrumentation. Existing
records still load and omit the new metrics when no assessment was recorded. For
before/after hallucination measurement, 25b will reuse the judge and blinded human
confirmation on final answers. That measurement is distinct from verifier verdicts.

## Planned verification (25)

- The first release covers knowledge answers on both routes. Refund reasons combine
  policy with order facts, and the refund path already checks its citations and
  return window.
- The verifier will check model-written text. Code-generated notices and handoff
  templates stay outside verification. A short configured list will cover generic
  phrases from the model.
- Each claim uses its paragraph's cited chunks. The verifier will never retrieve more
  evidence.
- The fast model will make one structured call per answer and supply a verbatim
  quote for each supported claim. The existing stack can validate those quotes
  without downloading a separate natural language inference model.
- Code will first check numbers, durations, amounts, percentages and model IDs
  against the cited chunks. A missing literal can be rejected before the model call.
- An unsupported claim will be removed. Losing the first claim or all substantive
  text fails that part. The existing partial-answer switch governs whether supported
  sibling parts can still be released.
- A failed or invalid verifier response will cause a handoff. Dependency failures
  use the dependency handoff reason.
- The grounding switch will provide a baseline with the previous graph behavior.
  Grounding settings will be captured in the E2E config hash.
- Sentence splitting is deterministic. The optional fast-model compound splitter
  will default off and be evaluated on dev.

The streaming API already emits answer tokens after the output guard. Verification
will add work before the first token. The release path will keep streaming the
checked answer, and 25b will measure the first-token latency and cost.
