# Eval run comparison

- Run A: `/tmp/atlas-24b/runs-rescored/e2e-dev-20261122-b864da21-88303db6`
- Run A Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run A config hash: `01e41fcd372fdbbe304d97a36630a463002b48c8fd40fa3e73bd5a1050ea5007`
- Run A datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run A split: dev
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B: `/tmp/atlas-24b/runs-rescored/e2e-dev-20261122-b864da21-36d4db0f`
- Run B Git SHA: `b864da21b6e6f9edc74a9f00791077199c374b91`
- Run B config hash: `86ab0df7bca96b2b0f97d481c5e714ba8a18d700c86978054068120f6fd403e8`
- Run B datasets: `{'eval_v1': DatasetVersion(version='v1', sha256='fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9')}`
- Run B split: dev
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | Paired n | A | B | Delta | 95% CI | McNemar p | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| citation_validity | 120 | 0.869444 | 0.881944 | +0.0125 | [-0.0152778, +0.0417014] | — | no significant change |
| false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| false_reject | 120 | 0.0916667 | 0.0833333 | -0.00833333 | [-0.0416667, +0.0166667] | 1 | no significant change |
| full_answer_rate | 30 | 0.9 | 0.966667 | +0.0666667 | [+0, +0.166667] | 0.5 | no significant change |
| graph_mrr_at_5 | 120 | 0.9875 | 0.9875 | +0 | [+0, +0] | — | no significant change |
| graph_recall_at_5 | 120 | 0.991667 | 0.995833 | +0.00416667 | [+0, +0.0125] | — | no significant change |
| latency_p50 | 150 | 18.0163 | 11.8499 | -6.16642 | [-7.66095, -4.58633] | — | better |
| latency_p95 | 150 | 31.964 | 30.3347 | -1.62925 | [-15.3258, +12.8486] | — | no significant change |
| noanswer_false_accept | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| part_recall_at_5 | 120 | 0.983333 | 0.991667 | +0.00833333 | [+0, +0.025] | 1 | no significant change |
| partial_answer_rate | 30 | 0 | 0 | +0 | [+0, +0] | 1 | no significant change |
| pass_rate | 150 | 0.726667 | 0.733333 | +0.00666667 | [-0.0133333, +0.0333333] | 1 | no significant change |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| colloquial-941f661aa51acdb3072362a0f17b4dfb52fa1e03191a9f4149e7da494e7acea9 | True | False | None | guardrail_blocked |
| cross_doc-02fb4ef75dd609300f08f3052872346051d9d67ef719353e5762ea90bd46bf53 | False | True | incomplete_evidence | None |
| cross_doc-8aada4ad28bafd1bc83b14dec38f03d4fe594392f36d7c2404cb9c5eb07d99f3 | False | True | guardrail_blocked | None |
