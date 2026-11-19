# 17a — Release gate: latency is reported, not blocking

**What**
I made a slower P95 latency a warning in the release gate.
P95 means the time that 95 percent of answers finish within.
I also removed a search tool from the gate workflow.
The workflow now uses grep, which every runner has.

**Why**
Latency here depends mostly on the machine and the network tunnel.
A busy runner could fail the gate when the code was fine.
False accepts and answer quality still block a release.
Without grep, a runner missing data would fail instead of skip.

**Number**
No number yet. I will measure it after the first smoke baseline on main.
A new test makes latency much slower on purpose.
The gate failed that test before the fix and passes it after.

**Trade-off**
The gate no longer stops a real slowdown by itself.
A person must read the warning in the gate summary.
Commit 33 adds latency targets, which are a better place for this.

**Likely follow-up question**
Q: Why not keep latency in the gate with a wider tolerance?
A: My runs share one laptop and an SSH tunnel to a server.
Any fixed tolerance would be a guess about that noise.
I will gate latency once I have a dedicated load test.
