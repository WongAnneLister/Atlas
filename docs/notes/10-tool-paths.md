# 10 — Order tools, complaints, fixed replies, and shared handoff

**What**
I connected order tools, complaint replies, and fixed replies to the graph.
I added a shared record for passing requests to human support.
I also added a command-line chat tool.

**Why**
I needed real order facts before answering order questions.
I bound every tool to the trusted customer identity.
I stopped tool loops when lookups kept failing or reached their step limit.

**Number**
No number yet. I will measure it in commit 13.
I checked fake models offline and a real provider against mock orders.

**Trade-off**
I chose to hand off instead of guessing after unresolved tool errors.
That can send valid requests to human support.
My real provider check passed, but it does not prove general answer safety.

**Likely follow-up question**
Q: Can the model read another customer's orders by changing its arguments?
A: I kept customer identity outside the tool's public arguments.
I injected it from the trusted conversation state.
I still need authentication before accepting that identity from an external caller.
