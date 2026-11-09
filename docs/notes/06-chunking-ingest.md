# 06 — Section chunks and a searchable index

**What**
I built section-based chunks for policies and products. I added BGE-M3, a model that changes text into lists of numbers. I wrote Milvus word search and vector search code.

**Why**
I needed stable source links before comparing search methods. I kept each chunk inside its source section. Without this link, I could not score retrieved evidence against expected sections.

**Number**
I built 206 chunks from 122 sections. Policy chunks use at most 512 tokens. I kept each of the 7 product sections whole.
Source: eval/reports/ingestion.md

**Trade-off**
I kept full manuals together for clear source links. My encoder averages smaller text windows to limit memory. This can blur exact facts in long manuals. Live ingestion remains blocked by missing runtime dependencies.

**Likely follow-up question**
Q: How will you check retrieval quality?
A: I still need to complete live database and model checks. Then I will compare both search methods in commit 08. I will keep the frozen questions and labels unchanged. Chunk counts alone do not prove search quality.
