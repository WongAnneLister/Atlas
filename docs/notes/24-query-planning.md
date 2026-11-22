# 24 — Routing and answering questions in parts

**What**
I added a step that looks for separate requests before choosing a route.
I classify each part to decide where the question goes.
I check the evidence for each knowledge part before answering it.

**Why**
The old route could miss a policy question inside a longer message.
I wanted to keep the useful answer when another part needs a person.
I send the unanswered parts and their search results to that person.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
A multi-part request can need extra model calls.
I keep the old route for ordinary single questions.
I also keep it when a part needs order tools or a refund.

**Likely follow-up question**
Q: What happens if search fails for one part?
A: I send the whole question to a person.
A partial answer requires a working search and strong evidence for the answered part.
