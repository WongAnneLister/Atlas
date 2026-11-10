# 13 — End-to-end evaluation, threshold sweep and hallucination review

**What**
I built a cached evidence-score sweep for dev and test splits.
I added resumable full-graph JSONL evaluation with outcome metrics.
I added a judge CSV, human confirmation import, and run comparison tool.

**Why**
The gate threshold must protect no-answer questions without tuning on test.
Without a full run, answer safety and latency would remain guesses.
The review CSV separates model flags from human confirmation.

**Number**
No number yet. I will measure it after Milvus and an LLM are configured.
Source: eval/reports/

**Trade-off**
The runners keep local caches and source text for reproducible debugging.
That uses disk space and requires careful config and dataset hash checks.
I kept the threshold unset because the required services were unavailable.

**Likely follow-up question**
Q: Why did you not set a demo threshold when the sweep could not run?
A: A placeholder would hide the real safety result and break the release rule.
The script fails closed until dev scores and held-out test scores exist.
