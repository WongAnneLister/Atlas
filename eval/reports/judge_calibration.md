# Judge calibration

- Audit fingerprint: `ee5079dcc100bfc934c72424db3416a3e7304206a73250cf5966758ca797d3f8`
- Source run SHA: `9ed1d576deca7c52494a51d728cc06a63d365815`
- Source run config hash: `7aa735a01dfeaa3c3b419d3c433f1da05cd30b60361e80fc0cb5433dfdf4f845`
- Source run models: `{"fast": "deepseek-flash", "main": "deepseek-flash"}`
- Dataset versions: `{"bitext": "bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443", "flipkart_faqs": "NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228", "maktek_faqs": "MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240", "philips_manuals": "InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84"}`
- Source eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Split: `test`
- Source run date: `2026-11-10T15:11:06.756261+00:00`
- Seed: `17`
- Bootstrap resamples: `2000`
- Audited rows with human labels: 0
- Judge status: kappa: n/a (0/30 labels)

30 more human labels are needed to reach 30.

The review sample includes every judge flag and a seeded sample of audited unflagged answers. Skipped rows are excluded. Estimates describe the labelled sample. Oversampling flags can shift recall and kappa relative to the full audit set.
Bootstrap intervals use the labelled rows. Kappa intervals omit draws with undefined agreement.
