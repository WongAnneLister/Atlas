# 28 — Only oversized catalog manuals are split

**What**
I now split a catalog section only when it is bigger than 4096 tokens. That is half the claim-check budget. Smaller product sections stay one chunk, as before. Only three whole manuals get cut into 512-token windows.

**Why**
My first rule split every product section over 512 tokens. The release check refused that index. One hair dryer entry became two short chunks. They outranked the model the customer asked about.

**Number**
The refused check kept hit at 5 at 160/160. But reciprocal rank fell from 0.9906 to 0.9510. Reciprocal rank is one over the rank of the first right section.
Source: eval/runs/catalog-split-28f/index-release-refused.md

**Trade-off**
I chose this rule after the refusal, and that check had two test items. So the next check is not fully blind. A 2989-token manual still stays whole. It fits the claim check but costs prompt tokens.

**Likely follow-up question**
Q: Why 4096 and not a value you tuned?
A: I took it from the failure itself. A source must fit the claim check with room to spare. Half of 8192 gives that room. I did not try several values and pick the best one.
