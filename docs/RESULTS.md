# Evaluation results

This file records measurements produced by repository scripts.
Numbers are never copied from other projects.

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
There is no comparable earlier end-to-end baseline, so no improvement delta is claimed.
