# 07 — Hybrid retrieval with reciprocal rank fusion

**What**
I built search using both meaning and exact words. I merged their ranked lists with reciprocal rank fusion. This method combines ranks instead of raw scores. I kept source ranks and scores visible in a search command.

**Why**
I needed both casual wording and exact model names. Either search method can miss useful evidence alone. I also added optional model spelling cleanup for word search.

**Number**
No number yet. I will measure it in commit 08.

**Trade-off**
I used both searches in sequence, adding work per query. I gave up score gaps when merging ranks. I kept raw scores for later checks. I checked a real catalog model because the example product was absent.

**Likely follow-up question**
Q: Does combining searches prove that the answer is supported?
A: I only built evidence retrieval in this commit. Search results alone cannot prove an answer is supported. I will add the evidence gate before generating knowledge answers.
