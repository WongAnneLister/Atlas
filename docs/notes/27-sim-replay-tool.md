# 27 — A replay tool for rare agent failures

**What**
I built a tool that replays a saved simulator chat against the current agent. It sends the exact recorded customer messages up to a chosen turn. It runs several arms, each with its own config switches, on the same code. I also put the order re-read fix behind a switch.

**Why**
The order re-read bug showed up on only two turns in one run. A simulated customer never repeats itself, so a new run may never hit the bug. Replaying the same messages lets me measure the fix on the exact failing chat.

**Number**
No number yet. I will measure it in the replay run that follows.

**Trade-off**
Replay fixes the customer side. So it cannot show how a customer reacts to a new reply. It answers only one question: does the agent now handle this turn. That is what a bug fix needs.

**Likely follow-up question**
Q: Why compare on and off instead of old and new code?
A: The same code removes every other difference between the runs. Only the switch changes. The project uses switches like this for every measured change.
