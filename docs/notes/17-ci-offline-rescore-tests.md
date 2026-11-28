# 17 — Re-scoring tests no longer need local data

**What**
I let the re-scoring tool take the scenario file as an input. Its three tests now build the scenarios from code into a temp folder. The scoring itself did not change.

**Why**
The tests read a scenario file that is never committed. My laptop had it, so local checks passed. The CI server did not, so main stayed red for two days.

**Number**
No number yet. This commit changes tests only, so no metric moves.

Source: No evaluation report for this commit.

**Trade-off**
The tests now score against freshly built scenarios, not the frozen file. If the two ever drift, these tests will not notice.

**Likely follow-up question**
Q: Why did you not see the red CI earlier?
A: I only ran local checks before each push. I now check CI after pushing.
