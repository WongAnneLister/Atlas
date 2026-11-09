# 06 — Fix service startup and verify database access

**What**
I fixed MinIO startup arguments and reduced build cache space. I made service startup work without installing the model tools.

**Why**
I found a repeated command that stopped the storage service. I needed healthy storage before checking the real database.

**Number**
I passed 1 real database integration test. I checked word search and vector search with fake vectors. I still lack a full model ingestion result.
Source: eval/reports/ingestion.md

**Trade-off**
I cached the verified model on the server. I avoided loading it beside existing services with little free memory. My client still needs the large weight file.

**Likely follow-up question**
Q: Does this prove retrieval quality?
A: I only checked database behavior. I still need real embeddings for every chunk. Then I will compare search quality with the frozen questions.
