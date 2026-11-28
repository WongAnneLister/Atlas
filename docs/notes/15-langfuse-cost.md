# 15 — Langfuse tracing and cost by intent

**What**
I added optional tracing with Langfuse, a tool that shows every step of a request.
Each turn gets tags for intent, path, gate result and handoff reason.
I also count model calls and tokens per model, without Langfuse.
The eval report now has a cost-by-intent table.

**Why**
Without traces, I could not see which step made a bad answer.
Without cost by intent, I could only guess which questions are expensive.
Tracing is off by default, so the app runs the same without it.

**Number**
Product questions used 15614 tokens per conversation on average.
Policy questions used 2644, so product questions cost 5.9 times more.
Both made about 1.8 model calls, and 98% of product tokens were input.
So the cost comes from long product sources, not from extra calls.
Source: eval/reports/archive/e2e-6cf0e48.md

**Trade-off**
I have no dollar figures yet, because I did not guess the prices.
The report says "price not set" until I add real prices.
Traces keep chunk ids and scores, not chunk text, so they are less complete.
Tags are written when a turn ends, so they show up a bit late.

**Likely follow-up question**
Q: How would you cut the cost of product questions?
A: The data says the prompt is the problem, not the number of calls.
I would send shorter product sources, like smaller chunks or only the top three.
Then I would rerun this report and check that false rejects do not rise.
