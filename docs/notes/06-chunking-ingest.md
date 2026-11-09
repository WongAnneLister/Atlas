# 06 — Verify real BGE-M3 ingestion

**What**
I cached the model at a fixed revision on my computer. I encoded source chunks as vectors, or lists of numbers. I stored these vectors in the project database.

**Why**
I needed proof beyond fake test vectors. I checked the full model file before loading it. I ran encoding without downloading anything.

**Number**
I stored 206 chunks from 122 sections. I used 244 text windows to retain full manuals. I also recorded 1 earlier database test with fake vectors.
Source: eval/reports/ingestion.md

**Trade-off**
I used my computer for encoding and the server for storage. I chose small batches to limit memory use. I kept manuals whole and averaged their window vectors.

**Likely follow-up question**
Q: Does this prove the answers are reliable?
A: I only proved model loading and database ingestion. I have not measured search or answer quality yet. I will compare retrieval methods using the frozen questions.
