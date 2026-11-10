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

The sweep and end-to-end runner are implemented in `eval/sweep.py` and `eval/e2e_eval.py`.
The threshold remains unset until a real dev score cache is collected.
The local environment currently has no reachable Milvus service and no configured LLM.
Therefore this commit records no fabricated safety, latency, token, or cost numbers.

Run the following after starting Milvus and setting `LLM_*` variables:

```bash
make sweep
make eval-e2e
make eval-judge
```

The generated reports include Git SHA, config hash, evaluation hash, model names, split, and date.
