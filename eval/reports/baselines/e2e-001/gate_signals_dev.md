# Evidence Gate Signal Analysis (Dev)

This analysis does not choose a threshold. It uses dev questions only.
No-answer questions are retrieved and reranked with the same settings.
A query without configured key terms gets key_hit = 1.0, a neutral value.

- Date: 2026-11-10
- Git SHA: 9ed1d576deca7c52494a51d728cc06a63d365815
- Config hash: `939d70232570de7bb170a3bd0735b6aa1a988130ec0a463d706211a472808e12`
- Eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Corpus hash: `60e259f600ed4ae895106d14385edcb6cfcf12071ec0219a32a936a209c5c6fd`
- Split: dev (150 questions)
- Models: BAAI/bge-m3 / BAAI/bge-reranker-v2-m3
- Dataset versions:
  - bitext: `bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443`
  - flipkart_faqs: `NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228`
  - maktek_faqs: `MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240`
  - philips_manuals: `InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84`

Values show mean, median, and p90 within each group and answerability label.

| Group | Label | N | Signal | Mean | Median | P90 |
|---|---|---:|---|---:|---:|---:|
| basic_policy | answerable | 30 | top_score | 0.9614 | 0.9980 | 0.9998 |
| basic_policy | answerable | 30 | good_count | 0.7667 | 1.0000 | 1.0000 |
| basic_policy | answerable | 30 | margin | 0.2662 | 0.0698 | 0.9139 |
| basic_policy | answerable | 30 | key_hit | 1.0000 | 1.0000 | 1.0000 |
| basic_policy | answerable | 30 | score | 0.8239 | 0.8492 | 0.8605 |
| colloquial | answerable | 30 | top_score | 0.9436 | 0.9887 | 0.9969 |
| colloquial | answerable | 30 | good_count | 0.7667 | 1.0000 | 1.0000 |
| colloquial | answerable | 30 | margin | 0.2192 | 0.0805 | 0.7265 |
| colloquial | answerable | 30 | key_hit | 1.0000 | 1.0000 | 1.0000 |
| colloquial | answerable | 30 | score | 0.8080 | 0.8460 | 0.8552 |
| cross_doc | answerable | 30 | top_score | 0.9894 | 0.9952 | 0.9996 |
| cross_doc | answerable | 30 | good_count | 1.0000 | 1.0000 | 1.0000 |
| cross_doc | answerable | 30 | margin | 0.0218 | 0.0109 | 0.0612 |
| cross_doc | answerable | 30 | key_hit | 1.0000 | 1.0000 | 1.0000 |
| cross_doc | answerable | 30 | score | 0.8480 | 0.8494 | 0.8528 |
| model_number | answerable | 30 | top_score | 0.9408 | 0.9477 | 0.9698 |
| model_number | answerable | 30 | good_count | 0.6667 | 0.6667 | 0.6667 |
| model_number | answerable | 30 | margin | 0.0973 | 0.0962 | 0.1823 |
| model_number | answerable | 30 | key_hit | 1.0000 | 1.0000 | 1.0000 |
| model_number | answerable | 30 | score | 0.7683 | 0.7661 | 0.7917 |
| no_answer | no_answer | 30 | top_score | 0.0057 | 0.0025 | 0.0177 |
| no_answer | no_answer | 30 | good_count | 0.0000 | 0.0000 | 0.0000 |
| no_answer | no_answer | 30 | margin | 0.0013 | 0.0005 | 0.0032 |
| no_answer | no_answer | 30 | key_hit | 0.9667 | 1.0000 | 1.0000 |
| no_answer | no_answer | 30 | score | 0.1480 | 0.1514 | 0.1590 |
