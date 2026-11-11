# Evaluation results

This file records measurements produced by repository scripts.
Numbers are never copied from other projects.

## Frozen full-graph baseline

`e2e-001` is the first complete real-model test-split full-graph run.
Its reports, charts, configuration, artifact checksums, and comparison instructions are frozen in
[`eval/reports/baselines/e2e-001/`](../eval/reports/baselines/e2e-001/README.md).
The original complete per-item run also has a separate local, gitignored baseline copy.
Later default reports may change; use the archived baseline for optimization comparisons.
This baseline includes the observed failures and does not establish answer accuracy.

## Retrieval baseline

| Experiment | Split | Recall@5 | MRR@5 | Source |
|---|---|---:|---:|---|
| Hybrid plus rerank | test | 1.0000 | 0.9938 | `eval/reports/retrieval.md` |

The retrieval report also contains the dense, BM25, hybrid, and ablation results.
These draft-set results exclude no-answer questions and do not prove answer safety.

## Commit 13 safety evaluation

An accepted outcome is a substantive knowledge, tool, or refund answer.
A handoff or fixed template is not accepted.
A false accept is an accepted no-answer question, divided by all no-answer questions.
A false reject is a rejected answerable question, divided by all answerable questions.
The sweep uses gate decisions; the end-to-end run uses final graph outcomes.
A no-answer question answered through the tools path still counts as a false accept.

| Experiment | Split | Threshold | False accept | False reject | Source |
|---|---|---:|---:|---:|---|
| Evidence gate only | dev | 0.17 | 0.00% | 0.00% | `eval/reports/threshold_sweep.md` |
| Evidence gate only | test | 0.17 | 3.33% | 0.00% | `eval/reports/threshold_sweep.md` |
| Full graph | test | 0.17 | 3.33% | 26.67% | `eval/reports/e2e.md` |

The sweep selected the lowest dev threshold with no false accepts.
The highest dev no-answer score was 0.1682; the gap was only 0.0018.
The held-out Cash App Pay question passed and received a substantive partial answer.
Both reports retain its ID; the full-graph report also records its route.
The threshold remains unchanged despite this test failure.
**Week 3's zero-false-accept gate did not pass.**

| Full-graph measurement | Test value | Source |
|---|---:|---|
| Accepted outcomes | 89/150 (59.33%) | `eval/reports/e2e.md` |
| Recall@5 inside graph | 0.6917 | `eval/reports/e2e.md` |
| Citation validity (gold-section overlap) | 0.5938 | `eval/reports/e2e.md` |
| Full-answer latency P50 | 19.9613s | `eval/reports/e2e.md` |
| Full-answer latency P95 | 38.6971s | `eval/reports/e2e.md` |
| Judge flags across all evaluation rows | 5.33% | `eval/reports/hallucination_review.md` |
| Human-confirmed hallucination rate | pending | `eval/reports/hallucination_review.md` |

Graph recall includes answerable questions routed away from retrieval.
It therefore measures the whole path, unlike the standalone retrieval baseline.
Citation overlap checks section identity; it does not establish factual support for every claim.
The local `eval/sets/hallucination_review.csv` is ready for human confirmation.

Measurements use the existing VPS Milvus index through SSH forwarding.
Both LLM roles use the locally configured DeepSeek Flash model in non-thinking mode.
Embedding runs on CPU; reranking uses MPS.
The threshold is selected from complete dev scores before evaluating test.
No questions, gold labels, weights, or test-driven thresholds were changed.

Run these targets with the SSH tunnel open and the local environment loaded:

```bash
make sweep
make eval-e2e
make eval-judge
```

The generated reports include Git SHA, config hash, evaluation hash, model names, split, and date.
Load `.env` with `python-dotenv` before invoking these targets.
The settings loader reads process environment variables; it does not load `.env` itself.
Keep model kwargs as valid JSON when exporting the environment.
For this Mac's MPS reranker, the actual command pattern is:

```bash
SUPPORT_AGENT__RETRIEVAL__RERANKER_DEVICE=mps uv run python - <<'PY'
import subprocess
from dotenv import load_dotenv

load_dotenv('.env')
for target in ('sweep', 'eval-e2e', 'eval-judge'):
    subprocess.run(['make', target], check=True)
PY
```

## Routing optimization round one

The application change is limited to the classification prompt.
It separates general rules and self-service guidance from personal order lookups and actions.
Models, retrieval, tools, gate weights, threshold, questions, and labels remain unchanged.

| Dev routing check | Original prompt | Candidate prompt | Source |
|---|---:|---:|---|
| Answerable questions targeting knowledge path | 96/120 (80.00%) | 118/120 (98.33%) | `eval/reports/routing_round1.md` |
| Authored policy/action controls | 20/22 (90.91%) | 22/22 (100.00%) | `eval/reports/routing_round1.md` |
| Answerable pairs with successful calls in both runs | 96/117 (82.05%) | 116/117 (99.15%) | `eval/reports/routing_round1.md` |

The primary comparison retains failed model calls.
The original prompt had three invocation failures; the candidate had none.
The successful-pair view also shows improvement without those availability differences.
Knowledge-route expectations follow benchmark construction, not human-reviewed intent labels.
Controls were authored before collection and are not representative held-out traffic.
No-answer questions have no invented intent gold; only route distributions are reported.
Neither comparison measures correct answers or evidence safety.

The candidate was frozen before full-graph test inference.
See `eval/reports/routing_round1_manifest.json` for its fingerprint and frozen inputs.
Methodology, saved prompt paths, reproduction commands, and limitations are in
[`docs/ROUTING_ROUND1.md`](ROUTING_ROUND1.md).

| Full-test outcome | Frozen baseline | Routing candidate | Source |
|---|---:|---:|---|
| False reject | 26.67% | 8.33% | `eval/reports/routing_round1_compare.md` |
| No-answer false accept | 3.33% | 3.33% | `eval/reports/routing_round1_compare.md` |
| Accepted outcomes | 89/150 (59.33%) | 111/150 (74.00%) | Baseline archive and `eval/reports/routing_round1_test.md` |
| Graph Recall@5 | 0.6917 | 0.9083 | Baseline archive and `eval/reports/routing_round1_test.md` |
| Citation overlap | 0.5938 | 0.7607 | Baseline archive and `eval/reports/routing_round1_test.md` |
| Full-answer latency P95 | 38.6971s | 36.2299s | Baseline archive and `eval/reports/routing_round1_test.md` |

The candidate completed the same frozen test questions with identical labels and effective settings.
Its prompt fingerprint was checked before and after inference.
The same Cash App Pay item remains a false accept; the safety target still fails.
The candidate was not revised using these results.
Improved acceptance does not prove answer accuracy, complete answers, or factual grounding.
Candidate judge flags and human-confirmed answer accuracy were not measured this round.

The candidate ran alone; the baseline shared compute and experienced SSH outages.
Both runs retain dependency failures, so the complete outcome delta is not solely a prompt effect.
The candidate log also records classification and answer-generation connection errors.
Fixed fallback outcomes must not all be described as semantic misclassifications.
Some knowledge handoffs have a passing gate; answer failures share the `low_evidence` reason.
More precise failure records are a follow-up, not a change to this frozen experiment.

## Manual acceptance observations

These checks are separate from frozen-set quality metrics.
`make chat Q='How long do I have to return an item?'` produced a cited answer.
Its route was `rewrite -> classify -> retrieve -> gate -> answer`.
The answer distinguished store policies instead of inventing a universal window.

`make chat Q='Can I pay with gold bars?'` did not meet the required handoff outcome.
It followed the knowledge answer route and cited related SuperCoins exclusions.
It acknowledged missing payment evidence and suggested a human, but created no handoff record.
This exposes a semantic coverage limit despite relevant retrieved words.
The example did not change the threshold or the frozen evaluation labels.

The refund picker accepted an offered order and resumed through order loading and policy retrieval.
A retrieval RPC failure during concurrent validation produced `low_evidence` and a handoff.
That verifies failure handling, not a successful cited refund decision.
After batch evaluation ended, the picker was retried with offered order `ORD-000012`.
It reached `refund_decide` and handed off with `policy_requires_human`.
The delivered fixture `ORD-000001` reached the same outcome when requested directly.
The required cited-decision demo remains open; neither run created an approved refund.

## Interpretation limits

The draft evaluation labels still require human review.
Report SHAs identify the base HEAD used during collection.
Uncommitted fixes changed cache persistence and report provenance, not gate scoring.
Sweep and end-to-end runs shared local model resources during this acceptance run.
Reported latency includes that contention and is not an isolated performance baseline.
SSH interruptions also caused fail-closed handoffs during the end-to-end run.
Those outcomes remain in the report rather than being selectively replaced.
First-token latency is unavailable without streaming callbacks.
Cost remains pending because no provider price table has been verified and configured.
The judge reviews accepted answers with cited text; it does not audit uncited tool answers.
Its flags are review suggestions, not human-confirmed hallucination labels.
The current judge-flagged denominator includes every evaluation row, including skipped rows.
An unflagged row without cited text is not evidence of a successful claim audit.
The original run has no earlier complete baseline; round one now compares against its frozen archive.
