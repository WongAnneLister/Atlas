# 22b — Index lifecycle evidence

**What**
I ran the whole index lifecycle on the real Milvus server. I did a full rebuild, a negative control, a one-section change and a rollback. A negative control is a change I expect the check to miss, written down first. I also fixed three bugs found on the way, each with a test.

**Why**
The release check had only run on fakes before. Fakes cannot show real vector noise or a real network. They also cannot show a real answer changing after a rollback. Without this run, "safe release and rollback" was only a claim.

**Number**
The full rebuild took 269.5 seconds. The one-section change took 26.2 seconds, because it embedded only 3 of 206 chunks. All three checks released with identical metrics: hit@5 160/160, no-answer gate passes 1/60. The app said 45 days after release and 30 days after rollback.
Source: eval/reports/index_lifecycle.md

**Trade-off**
The check has little power for small changes. The negative control changed 10 of 220 top-5 lists, but no metric moved. I also relaxed a rule: zero no-answer passes now applies to dev only. One test item already passed on the live index, so nothing could release.

**Likely follow-up question**
Q: What went wrong during the run?
A: The SSH tunnel to Milvus dropped many times. Five runs were cut short. Each one was marked invalid or refused, and the live index never moved. I then added retries for each question, and one later question survived a drop.
