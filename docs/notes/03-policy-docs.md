# 03 — Policy documents and product catalog

**What**
I merged FAQs into topic documents with stable section names. I built a product catalog from manual cover models. I added source mappings, cached topic choices, and checks for changed facts.

**Why**
Single FAQs make search tests too easy. Long documents make later chunking tests more useful. Keeping each store's scope helps avoid mixing conflicting policies.

**Number**
I built 12 documents with 122 sections. FAQ coverage reached 99.65%. I kept 7 product models.
Source: eval/reports/docs_build.md

**Trade-off**
I kept source wording instead of asking a model to rewrite policies. The text is less polished, but facts stay intact. Without a configured model, unmatched FAQs stay under other. Unclear licenses mean generated text stays local.

**Likely follow-up question**
Q: How did you check that merging preserved the facts?
A: I checked every covered question and answer against its source section. I also rejected new numbers and any extra prose. Cached choices and stable dates kept repeated builds identical.
