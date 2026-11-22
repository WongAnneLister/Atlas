# Index lifecycle evidence (commit 22b)

- Report git SHA: 5ccd15aa25bb68c29a24311951a4ac4a3e110f4b
- Release-check git SHA: 5ccd15aa25bb68c29a24311951a4ac4a3e110f4b (dirty: False)
- Release-check config hash: 374709e84c56206d4def377006c45d0aa321d1e4ae38e63626d4bc9b8126655a
- Models: BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181, BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
- Dataset versions: eval_v1 v1 (`fe82c904801b`), smoke v1 (`9ed7c618bd6e`)
- Eval split: dev-smoke (frozen dev items plus the frozen smoke items)
- Reranker device: mps
- Collected: 2026-11-22 UTC
- Release checks use retrieval and the evidence gate only. No LLM is called.

## Registry

| Build | Collection | Mode | Status | Parent | Docs hash | Release evidence |
|---|---|---|---|---|---|---|
| `828c9e89` | `support_chunks` | adopted | retired | — | `d6a143e7ab0c` | — |
| `f66917e9` | `support_chunks_bf66917e90d854635a44dbdac16e6e4c1` | full | released | 828c9e89 | `d6a143e7ab0c` | index-release-dev-smoke-20261122-5ccd15aa-e123956c2ab64a4f9fd6d796dba81fc4 |
| `ef8bc336` | `support_chunks_bef8bc336eb7d4e00946007771ff96a1b` | incremental | retired | f66917e9 | `8e8efe061f0a` | index-release-dev-smoke-20261122-5ccd15aa-2fe3eb2d5e9f47e9b958510b9ddb67b2 |

Alias `support_chunks_live` now targets `f66917e9`; previous `ef8bc336`.

## Every release-check run

All collection attempts are listed, including those cut short by drops of the SSH
tunnel to Milvus. Decisions below use only the complete MPS runs. An attempt with too
many errors is invalid; one with an unassessed no-answer item is refused. The alias
never moved on a failed attempt. Per-question retries were added after the CPU attempts.

| Started (UTC) | Collection | Device | Minutes | Items with errors | Items retried |
|---|---|---|---:|---:|---:|
| 2026-11-21 12:54 | adopted | cpu | 102 | 0/220 | 0 |
| 2026-11-21 14:36 | full rebuild | cpu | 76 | 69/220 | 0 |
| 2026-11-21 15:54 | full rebuild | cpu | 212 | 2/220 | 0 |
| 2026-11-21 15:55 | negative control | cpu | 211 | 2/220 | 0 |
| 2026-11-21 19:26 | full rebuild | cpu | 53 | 138/220 | 0 |
| 2026-11-21 19:26 | negative control | cpu | 53 | 138/220 | 0 |
| 2026-11-22 02:21 | adopted | mps | 61 | 0/220 | 0 |
| 2026-11-22 02:21 | negative control | mps | 61 | 0/220 | 0 |
| 2026-11-22 03:22 | full rebuild | mps | 24 | 0/220 | 0 |
| 2026-11-22 03:48 | incremental | mps | 31 | 0/220 | 1 |

## 1. Adoption

`support_chunks` was registered as build `828c9e89` without a release check. Its chunks matched the on-disk documents exactly.

## 2. Identical full rebuild

- Embedded 206 chunks, copied 0, total 206, in 269.5 s.
- Stored vectors against the adopted collection: 0/206 chunks bit-identical, max absolute difference 3.82e-06, minimum cosine 0.9999999996.

### Release check: full rebuild against adopted

- Outcome under the current rule: **release**
  - Note: These no-answer items already pass the gate on the live build; a later check, not this one, stops them: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Outcome under the planned rule (zero passes on every no-answer item): **refuse**
  - Reason: No-answer gate passed: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Candidate run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-e123956c2ab64a4f9fd6d796dba81fc4`
- Live run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-8814e160be76483ab317f1c1fb689503`

| Metric | Candidate [95% CI] |
|---|---|
| gate_pass | 160/160 · 100.00% [100.00%, 100.00%] |
| hit_at_5 | 160/160 · 100.00% [100.00%, 100.00%] |
| noanswer_gate_pass | 1/60 · 1.67% [0.00%, 5.00%] |
| rr_at_5 | 0.9906 [0.9781, 1.0000] |

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| hit_at_5 | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| rr_at_5 | 160 | 0.990625 | 0.990625 | +0 | [+0, +0] | — | no significant change |
| gate_pass | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_gate_pass | 60 | 0.0166667 | 0.0166667 | +0 | [+0, +0] | 1 | no significant change |

- Items whose top-5 chunk list differs from the live run: 0/220; largest gate-score difference: 0.

## 3. Negative control

Expectation, written before any release output was seen:

> Written 2026-11-21T12:50:31Z, before any 22b release-check output was seen.
>
> Negative control: the 22a release check on support_chunks_eval_no_heading (chunks embedded
> without the heading prefix) against the live run of the step-3 build.
>
> Expectation: release, with no significant paired change. Reason: eval/reports/retrieval.md
> shows hybrid_heading_off Recall@5 0.9333 against hybrid 0.9583 on test (dev: 0.9542 against
> 0.9667), before reranking. The release check measures after reranking, which sees the same
> chunk text in both collections. A gap that small gives McNemar too few discordant pairs.
> So this control most likely shows the limit of the check's power, not a refusal.
> The no-answer rule (zero gate passes) applies either way and could still refuse it.

### Release check: no-heading collection against live

- Outcome under the current rule: **release**
  - Note: These no-answer items already pass the gate on the live build; a later check, not this one, stops them: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Outcome under the planned rule (zero passes on every no-answer item): **refuse**
  - Reason: No-answer gate passed: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Candidate run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-daec6da178ed4da8ac45ff4b6c0a4437`
- Live run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-e123956c2ab64a4f9fd6d796dba81fc4`

| Metric | Candidate [95% CI] |
|---|---|
| gate_pass | 160/160 · 100.00% [100.00%, 100.00%] |
| hit_at_5 | 160/160 · 100.00% [100.00%, 100.00%] |
| noanswer_gate_pass | 1/60 · 1.67% [0.00%, 5.00%] |
| rr_at_5 | 0.9906 [0.9781, 1.0000] |

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| hit_at_5 | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| rr_at_5 | 160 | 0.990625 | 0.990625 | +0 | [+0, +0] | — | no significant change |
| gate_pass | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_gate_pass | 60 | 0.0166667 | 0.0166667 | +0 | [+0, +0] | 1 | no significant change |

- Items whose top-5 chunk list differs from the live run: 10/220; largest gate-score difference: 6.66e-05.

## 4. One-section change

- Plan: 1 changed, 0 added, 0 deleted, 121 unchanged; mode incremental.
- Incremental build: embedded 3 chunks, copied 203, total 206, in 26.2 s (full rebuild: 206 embedded, 269.5 s).

### Release check: incremental against full

- Outcome under the current rule: **release**
  - Note: These no-answer items already pass the gate on the live build; a later check, not this one, stops them: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Outcome under the planned rule (zero passes on every no-answer item): **refuse**
  - Reason: No-answer gate passed: no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3.
- Candidate run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-2fe3eb2d5e9f47e9b958510b9ddb67b2`
- Live run: `eval/runs/index-release-dev-smoke-20261122-5ccd15aa-e123956c2ab64a4f9fd6d796dba81fc4`

| Metric | Candidate [95% CI] |
|---|---|
| gate_pass | 160/160 · 100.00% [100.00%, 100.00%] |
| hit_at_5 | 160/160 · 100.00% [100.00%, 100.00%] |
| noanswer_gate_pass | 1/60 · 1.67% [0.00%, 5.00%] |
| rr_at_5 | 0.9906 [0.9781, 1.0000] |

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| hit_at_5 | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| rr_at_5 | 160 | 0.990625 | 0.990625 | +0 | [+0, +0] | — | no significant change |
| gate_pass | 160 | 1 | 1 | +0 | [+0, +0] | 1 | no significant change |
| noanswer_gate_pass | 60 | 0.0166667 | 0.0166667 | +0 | [+0, +0] | 1 | no significant change |

- Items whose top-5 chunk list differs from the live run: 0/220; largest gate-score difference: 0.00137.

### Real app after release (`make chat`)

> Customer: For the generic store: What is your return policy?
> Agent: You can return products within 45 days of purchase for a full refund, provided they are in their original condition and packaging. Detailed instructions are on the Returns page. [1]
> Trace: input_guard -> rewrite -> classify -> retrieve -> gate -> answer -> output_guard

### Real app after `make index-rollback`

> Customer: For the generic store: What is your return policy?
> Agent: You can return products within 30 days of purchase for a full refund, provided they are in their original condition and packaging. [1]
> Trace: input_guard -> rewrite -> classify -> retrieve -> gate -> answer -> output_guard
