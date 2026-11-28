# 13 — Routing checks for "cancel and refund"

**What**
I added three routing checks before testing the new classifier line. Two ask to cancel and get the money back, and should reach the refund path. One only asks to cancel, and should stay on the order path.

**Why**
No existing check covered a request that asks for both things. The frozen intent set cannot run, because it is tied to an older prompt. So I used the routing method from the last classifier change.

**Number**
No number yet. I will measure it in the routing runs that follow.

**Trade-off**
I wrote the checks myself, so they are boundary tests, not a benchmark. Three items cannot show a rate. They only catch the case breaking.

**Likely follow-up question**
Q: Why not rebuild the intent set to include these cases?
A: The project forbids a silent rebuild of that frozen set. A rebuild would also change what earlier numbers mean.
