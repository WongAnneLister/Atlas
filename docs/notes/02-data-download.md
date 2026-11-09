# 02 — Download datasets and check licenses

**What**
I built a script that downloads four public datasets. Each one is pinned to an exact commit hash. A manifest file records every file hash, row count and column. I also built a license report that reads each dataset card.

**Why**
If data floats on the latest version, my results can change without warning. Pinning makes every later number repeatable. The license report tells me what I may publish. Breaking a license would be worse than a bad metric.

**Number**
No number yet. I will measure retrieval quality in commit 08.

**Trade-off**
The main dataset in my plan was deleted from Hugging Face. I switched to Flipkart help FAQs and a few Philips manuals. That gives me very few products for model-number questions. Two sources are "unclear", so reviewers must download them themselves.

**Likely follow-up question**
Q: Why mark a dataset "unclear" if its card says Apache?
A: The uploader did not write that text. Flipkart and Philips own it. A license only counts if the owner gave it. So I chose the safe default.
