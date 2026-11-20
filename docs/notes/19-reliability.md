# 19 — Reliability when dependencies fail

**What**
I added deadlines and retries around calls to models and data services.
I added a circuit breaker that pauses calls to a failing service.
I made repeated refund writes return the saved request.
I added a shared chat lock and counters for service failures.

**Why**
A slow service can leave a customer waiting.
A failed search can leave the model without evidence.
I sent these cases to human support when the checks could not finish safely.

**Number**
No number yet. I will measure it in commit 19a.

**Trade-off**
Retries can make a single answer take longer.
I capped the wait and stopped calls early when failures piled up.
Each worker keeps its own record of a failing service.

**Likely follow-up question**
Q: What happens if the system cannot rank the search results?
A: I discard the search results and let the evidence check fail.
I hand off the question before the model tries to answer it.
