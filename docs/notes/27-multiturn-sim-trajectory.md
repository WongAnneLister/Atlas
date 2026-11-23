# 27 — Multi-turn user simulator and trajectory metrics

**What**
I built a 60-scenario multi-turn test suite across twelve support categories.
I added an isolated user simulator that only sees visible chat messages.
I built an API runner that handles order-picker interrupts and records full transcripts.
I also added trajectory metrics for success, tool use, retention, loops, and tokens per turn.

**Why**
Single-turn tests miss bugs that only show up in real chats.
An agent can forget an order number, loop on a tool, or re-ask known facts.
We need a multi-turn baseline before changing context layout and memory in commits 28-30.
Running through the real API also checks interrupts and customer isolation end to end.

**Number**
Across 30 nightly test runs, task success was 36.67% with 0.0943 repeat variance.
Wrong customer access was 0 of 30, and fact retention was 16.67%.
Handoff appropriateness was 33.33%, with 0.00% loop rate and 0.00% run errors.
Source: eval/reports/sim.md

**Trade-off**
A simulated user can make mistakes or drift out of character during long chats.
Running 60 multi-turn chats three times also costs much more than single-turn evals.
I added a 10-scenario nightly CI subset and a manual transcript validity review.
That keeps daily costs down while separating simulator errors from agent errors.

**Likely follow-up question**
Q: How do you stop the simulator from cheating or inventing facts?
A: The simulator never sees internal agent state, traces, or tool outputs.
Its prompt locks it to the scenario facts and hides private details until asked.
We also manually review ten sampled transcripts to verify it stayed in role.
