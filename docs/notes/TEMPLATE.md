# Interview note template

Every commit ends with one note: `docs/notes/NN-<slug>.md` (same `NN` and slug as the commit prompt file).
The note is what the author will **say out loud in an interview**. Write it for speaking, not for reading.

## Plain-English rules (must follow)

1. **Short sentences.** Max 15 words each. One idea per sentence.
2. **Common words.** Write like you talk to a smart friend who is not an expert. No "leverage", "utilize", "robust", "seamless", "cutting-edge".
3. **Explain a term the first time.** Example: "I use RRF. It merges two ranked lists by rank, not by score."
4. **First person, past tense for what was done.** "I built…", "I measured…", "I chose…".
5. **No nested clauses.** Avoid "which", "whereas", "given that" chains. Split into two sentences.
6. **Numbers only from reports.** Every number must come from a file in `eval/reports/` or `eval/runs/`. Put the path in brackets after the section. If there is no number yet, write: "No number yet. I will measure it in commit NN."
7. **Honest.** If the result was worse than the target, say it plainly, and say what you will try next.
8. **Length.** Each section 2–4 sentences. The whole note should take about 60–90 seconds to say.

## Format (copy exactly)

```markdown
# NN — <commit title>

**What**
<2–4 short sentences: what I built in this commit.>

**Why**
<2–4 short sentences: the problem it solves. What breaks without it.>

**Number**
<2–4 short sentences with real numbers, or "No number yet…".>
Source: <path to report>

**Trade-off**
<2–4 short sentences: what I gave up, what it costs (latency, money, complexity, false rejects), and why it was worth it.>

**Likely follow-up question**
Q: <the one question an interviewer is most likely to ask next>
A: <2–4 short sentences answer.>
```

## Example (style only — numbers are placeholders)

```markdown
# 11 — Evidence gate and the knowledge path

**What**
I added a check before the model writes an answer. It scores the search results with four signals. If the score is too low, the bot hands off to a human. If it passes, the bot answers and cites each source.

**Why**
A model will always try to answer. Without the check, it makes things up when the docs have no answer. In customer service, a wrong answer is worse than "let me get a human".

**Number**
On the dev set, the top rerank score was [X] on average for answerable questions. It was [Y] for out-of-scope questions. That gap is why one threshold can separate them.
Source: eval/reports/gate_signals_dev.md

**Trade-off**
Some good questions now go to a human. That costs human time. I accepted it, because a made-up refund rule costs more. I pick the exact threshold later, with a sweep on the dev set.

**Likely follow-up question**
Q: Why check before generation, not after?
A: Checking first is cheaper. A weak question never reaches the big model. It is also safer, because nothing wrong is ever written. I still check claims after generation, but that is a second layer.
```
