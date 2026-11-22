# Claim verifier

- Verifier SHA: `07cf8f59de05b07752e746a80e0b597f562f06de`
- Verifier config hash: `45c3fc9e7288e5635716ef2d3d97e1c39669989966e782397ddc45442f57ebaf`
- Dataset: claims_v1 v3 (`ec330eea3fa6827e4f7c8b43df359b1d8f9892437aba841063691fec9061d782`)
- Models: fast=deepseek-flash, main=deepseek-flash
- Run date: 2026-11-22T16:12:45.206297+00:00
- Eval split: dev
- Recall target: 90.00%
- Interval level: 95%

| Split | Group | Scored / total | TP | FP | FN | Precision | Recall | F1 | Target |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| dev | real | 80/80 | 0 | 0 | 3 | n/a | 0.00% [0.00%, 56.15%] | 0.00% [0.00%, 71.92%] | below target |
| dev | synthetic | 60/60 | 60 | 0 | 0 | 100.00% [93.98%, 100.00%] | 100.00% [93.98%, 100.00%] | 100.00% [96.90%, 100.00%] | met |
| dev | synthetic / amount | 5/5 | 5 | 0 | 0 | 100.00% [56.55%, 100.00%] | 100.00% [56.55%, 100.00%] | 100.00% [72.25%, 100.00%] | met |
| dev | synthetic / duration | 5/5 | 5 | 0 | 0 | 100.00% [56.55%, 100.00%] | 100.00% [56.55%, 100.00%] | 100.00% [72.25%, 100.00%] | met |
| dev | synthetic / model | 10/10 | 10 | 0 | 0 | 100.00% [72.25%, 100.00%] | 100.00% [72.25%, 100.00%] | 100.00% [83.89%, 100.00%] | met |
| dev | synthetic / number | 20/20 | 20 | 0 | 0 | 100.00% [83.89%, 100.00%] | 100.00% [83.89%, 100.00%] | 100.00% [91.24%, 100.00%] | met |
| dev | synthetic / uncited_sentence | 20/20 | 20 | 0 | 0 | 100.00% [83.89%, 100.00%] | 100.00% [83.89%, 100.00%] | 100.00% [91.24%, 100.00%] | met |

Partial verdicts count as unsupported. Real claims without a label are excluded.
Real-claim label sources: model_draft 80. `model_draft` labels were drafted by a model and not reviewed by the author.
Synthetic negatives contain no positive support examples, so their precision cannot
measure how often the verifier would reject supported claims.
F1 intervals transform the Wilson interval for TP / (TP + FP + FN).
