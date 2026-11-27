# 28 — Answers start with the key fact

**What**
Both answer prompts now ask the model to open with the direct answer. They forbid a summary, heading or general opening line. The grounding rules did not change.

**Why**
The claim check treats a part's first sentence as its main claim. In one long chat, the model opened with a broad summary line. The checker could not support it, so it dropped the whole part. The verified fact in the next sentence was lost with it.

**Number**
No number yet. I will measure it in the dev before and after runs that follow.

**Trade-off**
A prompt change touches every answer, not just this case. The model may also refuse more often, since every sentence now needs a quote. I wrote the adoption rule before any run, and I revert if dev gets worse.

**Likely follow-up question**
Q: Why not relax the claim check instead?
A: That would loosen a safety check to fit one answer style. Asking for the fact first keeps the check strict. It also gives the customer the answer sooner.
