# Chunk size limits

How big one retrieved chunk may be, why a few chunks were far over the limit, what is in
place now, and what a production-grade design would add. Numbers here are copied from the
reports and commits named next to them; re-run those to check them.

## What went wrong

`chunk.max_tokens` is 512, but under the default `token` strategy the chunker kept every
`product.*` section whole. That exception dates from commit 06, when a catalog entry was a
short spec row and "one product, one chunk" kept its facts together. Philips user manuals
were later added under the same `product.*` sections, and the exception kept them whole too.
Nothing checked the size of the chunks that came out, so the rule "512 tokens" was never
verified against the built index.

Four catalog chunks in index build `4aece1a3` held a whole manual: `product.24E1N2300A` and
`product.27E1N2300A` (12331 tokens each), `product.HD928X` (7967) and `product.TAH6206`
(2989).

Found in the 27c test rerun (`eval/reports/memory_short.md`): in one long chat the answer
prompt reached 46460 tokens against its 12000-token budget, the claim check (`verify`,
8192-token budget) then raised `ContextOverflow`, and the turn handed off with
`low_grounding`. The agent failed closed, but the call was wasted and the turn unanswered.
The 28c replay (`eval/reports/answer_budget_replay.md`) shows the same turn.

## Defences, in the order a request meets them

| Layer | What it does | Status |
|---|---|---|
| Ingest-time hard cap | `chunk.hard_max_tokens` (4096; validated >= `max_tokens` and `product_whole_max_tokens`, <= half the verify budget). `make ingest` (`load_chunks`) and every index build (new and copied rows, before embedding) fail with `ChunkSizeError` listing chunk_id, section_id and tokens of each chunk over it; nothing is truncated. Build results and `ingest_run.json` record count, max, p99 and count over `max_tokens`; each release report has a line for the candidate and the live build; `make eval-chunk-sizes` checks saved builds. The cap is left out of the index fingerprint. Adoption of an existing collection and the release decision itself do not check it. | 28g, added after build `369f54d6` was released |
| Split rule for catalog sections | A `product.*` section longer than `chunk.product_whole_max_tokens` (4096, half the verify budget) is cut into `chunk.max_tokens` windows; shorter ones stay whole. | `00114f5`; released as build `369f54d6` on the scratch registry and local Milvus copy (paired check: every metric identical to `4aece1a3`; `eval/runs/catalog-split-28f/`) |
| Answer prompt fit | If the answer prompt is over budget, drop the lowest-ranked source first, keep one per question part; if one source alone does not fit, hand off with `context_overflow` and do not call the model. | `ca51a9e` (28c), on main |
| Claim check batching | `verify` halves its claim batch on overflow; a single claim whose sources do not fit still raises and the turn hands off. | `a15a011`, on main |

The layers are meant to overlap: the cap stops a bad chunk from being indexed, the split
rule keeps known large sections usable, and the prompt-side fits keep a missed case from
reaching the model at any size.

## Decision log

1. 28c (`ca51a9e`): prompt-side fit. It removed the overflow and cut tokens, but on the long
   chat the fitted turn still handed off: the HD928X manual was dropped from one question
   part but stayed visible (same global source number) under another, the model cited it for
   the first part, and the part-scoped quote check rejected it (`invalid_evidence`, then
   `invalid_answer`). The root cause was the unsplit manuals.
2. First split rule (`9a9ac2d`): cut every product section over 512. The paired index release
   check refused candidate `91f848b9`: hit@5 and gate pass unchanged (160/160), RR@5 fell
   from 0.9906 to 0.9510. All 13 regressions were "I mean BHD308/10 or BHD340/10, rather
   than BHD510/03" questions: the 635-token BHD510/03 entry became two windows, both headed
   with its model number, and both outranked the gold section. Not released, no override.
   Evidence: `eval/runs/catalog-split-28f/`.
3. Second split rule (`00114f5`): split only above 4096 tokens. The limit comes from the
   defect (a source kept whole must fit the verify prompt with room to spare), not from
   results. It was chosen after the refusal above, and that check's item set includes 2
   test items whose regression had been seen; this is recorded in the commit and PROGRESS.

## Known limits of the current design

- 4096 is a pragmatic threshold, not a clean rule. A section of 4000 tokens is still one
  chunk; it fits every budget, but it is a weak retrieval unit.
- Manual windows are cut by token count, not by the manual's own structure, so a window can
  start mid-sentence or mid-table.
- Every window of a manual repeats the product heading, so several windows of one product
  can fill the top ranks for a query that names that product, as in decision 2.
- The answer node renders a source once per question part that retrieved it, so a shared
  large source counts against the budget more than once.

## Production-grade target

What a production retrieval stack usually adds, in rough order of value for this project:

1. **Hard size invariant at ingest.** One cap for every chunk, enforced by the build, with
   the size distribution in every build record and release report. Cheapest and most
   important: it turns a silent data problem into a failed build.
2. **Structure-aware splitting.** Split manuals by their headings (safety, setup, warranty,
   troubleshooting) first, then by tokens only inside a section that is still too long. Keep
   tables and spec rows whole. Each chunk then has one topic.
3. **Group results by section at retrieval time.** Keep at most one or two chunks per
   section in the top-k (Milvus can group search results by a field). This is what removes
   the decision-2 failure mode, and it would allow splitting every section to `max_tokens`
   without a size exception.
4. **Small-to-big context.** Retrieve with small chunks for precision, then give the model
   the neighbouring windows of the same section, within the prompt budget.
5. **Budget-aware prompt assembly.** Already in place (28c): the last line of defence.
6. **Release gating on retrieval and size.** The paired release check already gates
   retrieval metrics and (28g) reports each build's chunk sizes; it does not yet refuse a
   build whose max chunk size exceeds the cap. Builds made since 28g cannot exceed it.

Items 2 to 4 change ranking and must go through the paired release check and an end-to-end
before/after like any other retrieval change.
