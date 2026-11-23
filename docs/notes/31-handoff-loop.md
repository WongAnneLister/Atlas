# 31 — Human handoff queue, console, and improvement loop

**What**
I added a `handoffs` table, an atomic queue store, and a checkpointed `human_mode` route.
I built `/api/agent/*` endpoints, a live SSE reply stream, and a static `/console` page.
I added `make loop-report` to turn labelled resolutions into doc gaps and eval candidates.
I also documented the architecture and `human_mode` design choice in `docs/HANDOFF.md`.

**Why**
A production handoff needs a human to claim, inspect, reply, and resolve the ticket.
Without `human_mode`, follow-up customer messages would keep hitting the AI and waste model calls.
Showing the frozen AI snapshot lets agents see exact retrieval scores without re-running anything.
Labelled resolutions close the loop by turning real failures into new docs and eval cases.

**Number**
No number yet.
Human agents must label real handoffs before loop metrics mean anything.
I will measure live handoff and feedback rates in commit 32.

**Trade-off**
I used a checkpointed `human_mode` flag instead of a LangGraph `interrupt()` call.
An interrupt only takes one resume input, while customers may send several follow-up messages.
In-process SSE delivery (`HandoffEventBroker`) keeps the demo simple with no extra broker service.
A multi-worker deployment would later swap that in-process pub-sub for Redis pub-sub.

**Likely follow-up question**
Q: How do you prevent two agents from claiming the same handoff at once?
A: `claim()` runs one conditional SQL update that checks `status = 'open'`.
The database locks the row inside the transaction and checks `rowcount == 1`.
Only the first agent succeeds, and every other concurrent caller gets HTTP 409.
