# 27 — Recall probes after a handoff, and probes that give the answer away

**What**
After a handoff, the simulated customer is reminded the assistant is still there. It must keep to its script. I also stopped scoring a recall probe when the customer repeats the fact in it.

**Why**
On dev, one customer said "I'll wait for the human" on every later turn. So its recall questions were never asked. Other probes named the order themselves, and repeating it back tests no memory.

**Number**
No number yet. I will measure it in the dev rerun that follows.

**Trade-off**
The reminder makes the customer act less like a real person after a handoff. Self-correction probes now drop out, because the script makes them name the order. Those scenarios need a new probe wording to test recall.

**Likely follow-up question**
Q: How do you know the probe was a real recall question?
A: The probe must reach its turn and must not contain the fact. I also read the dev transcripts by hand. That is how I found both problems.
