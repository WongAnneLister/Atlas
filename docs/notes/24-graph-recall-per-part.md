# 24 — Graph recall for split questions

**What**
I changed how two retrieval metrics read a split question. Graph recall and MRR now check each part's own top five results. A question that was not split is scored exactly as before.

**Why**
The release gate failed on graph recall after query planning. Every failing item was a split question. The stored list puts the first part's results first. So the second part's sources never reached its first five places.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
I changed a metric because the gate failed, which needs care. I wrote a test that failed before the change. I will report the gate result both before and after the change.

**Likely follow-up question**
Q: Did you change the metric just to pass the gate?
A: No, the old reading ignored the second part's search. I checked all nine failing items by hand. Each gold source was in some part's top five.
