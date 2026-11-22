# Cross-document failure analysis

Generated offline by `make eval-cross-doc-failures` from saved per-item graph records. The smoke runs repeat test items, so counts are shown per run.

Acceptance is the saved graph outcome. Section hits use the first five recorded ranks including repeated sections. The knowledge retrieval node can also run after a tool fallback. Missing-section counts use rejected rows that reached this node and have no recorded retrieval error. Failure patterns can overlap. A dash marks an empty or unavailable value.

## e2e-test-20261117-266c1e85-legacy

- Source `eval/runs/e2e-test-20261117-266c1e85-legacy`
- Git SHA `266c1e85a85208a3c5592a5b5ed1f995a8c6f9ea`
- Config hash `cd882d7fc98e06610ddee32fce7c958890b72ca189c42fcf30efe50c00ba8f7b`
- Eval file hash `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Corpus hash `60e259f600ed4ae895106d14385edcb6cfcf12071ec0219a32a936a209c5c6fd`
- Recorded at 2026-11-17T05:51:19.850757+00:00 for split `test`
- Models `{"fast": "deepseek-flash", "main": "deepseek-flash"}`
- Dataset versions `{"bitext": "bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443", "flipkart_faqs": "NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228", "maktek_faqs": "MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240", "philips_manuals": "InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84"}`

| Outcome or observed pattern | Count |
|---|---:|
| Cross-document items | 30 |
| Accepted | 23 |
| Rejected | 7 |
| Reached knowledge retrieval | 24 |
| Reached knowledge retrieval with every gold section in the top 5 | 24 |
| Recorded gate passed | 24 |
| Rejected before knowledge retrieval | 6 |
| Rejected with exactly one gold section missing after retrieval | 0 |
| Rejected with multiple gold sections missing after retrieval | 0 |
| Rejected with a failed gate | 0 |
| Coverage marked a part unsupported | 1 |
| Coverage relied on absence | 0 |
| Invalid quote or quote source | 0 |
| Dependency unavailable | 0 |

| Item | Initial path | Reached knowledge retrieval | Gold in recorded top 5 | Gold absent from recorded top 5 | Gate | Handoff reason | Answer status and error | Accepted |
|---|---|---|---|---|---|---|---|---|
| `cross_doc-0cb34ef4afd01de7e99fcad1a039179cdea74b413a5dbba2c5e2ac6c2268ce2d` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-13593f326a6fc61b0c37a8f0b77ba5226520a324beda0849279093a9bfd9fa3b` | `E` | no | — | `orders.maktek_faqs.generic-store.5c8d1db88fb2b1a907bd1a2f6b2bc37ade7502357c8948e1c118e2ebce589b43`, `refunds.maktek_faqs.generic-store.5c8d1db88fb2b1a907bd1a2f6b2bc37ade7502357c8948e1c118e2ebce589b43` | — | — | `not_attempted` | no |
| `cross_doc-1a3b877478fe5a7e257e5d84a1ea9eeec3b1bb57d49f07d7043167a9e395cfa2` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-204b720e66ada7a260764e0c70c5315b6effec6918c8a3872a1aa048de9aa043` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-2b337f04b48dd1554f6aaf1d3acc81d9e4b7229083e7bd0de4751fb071fc6674` | `C` | no | — | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775` | — | `order_not_found` | `not_attempted` | no |
| `cross_doc-2f9a30ebcd3e524f0d41884fda7b9ee8ab1fd3a30fd3dbc06114abb4ed9bf680` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-3312b6e8ecf5d4916a41cbf391aefdf4d6f0715b41c76d9a89118862e31be765` | `B` | yes | `refunds.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `membership.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-3c7e761ce46a737c435da2ea73ebed7672cbe6c2a2af17c841c9465e76300984` | `A` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-4188c9824c8648bd82230802a837bdf76e4a9aec72cf806ab2dc4a22923ffde9` | `C` | no | — | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `shipping.flipkart_faqs.others-shipping.9b7d1ed201726532775a77e845bd84447b4c666bc1fab3e15b8a896ce8a440fe` | — | `order_not_found` | `not_attempted` | no |
| `cross_doc-45ddcc1faa1d0778b2ad98c5a860265156573d965fc3e405f3f4cd562198285b` | `E` | no | — | `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7`, `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46` | — | — | `not_attempted` | no |
| `cross_doc-46eb19eb0956c3e6b9422fc5952778443054088afa10f205449b9d734cecb230` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e` | `A` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | `incomplete_evidence` | `insufficient_coverage` | no |
| `cross_doc-4beb27da2e6cb0bc781629d52172f5d7a7202b24df365bc540db8b20cb4dbcd7` | `A` | yes | `payments.flipkart_faqs.others-gift-cards.031f7b62c9b9cc45f3f0efc902093c5bd766bd45ea60e0a944e5417d010cb5ef`, `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-5532f722baa093833d5d9dab02f43fe3c50b23e73482554b4ba38cadb47a7a90` | `E` | no | — | `payments.flipkart_faqs.others-gift-cards.031f7b62c9b9cc45f3f0efc902093c5bd766bd45ea60e0a944e5417d010cb5ef`, `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3` | — | — | `not_attempted` | no |
| `cross_doc-55412f89896e4090fdda7638844a8d8d96945896d1dc7391539a3f2e3e8a9db1` | `B` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-5863219c58899f756f69d348f0891f43129aaa91579a4ef8aae855c1e0868a7c` | `E` | no | — | `orders.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44` | — | — | `not_attempted` | no |
| `cross_doc-5b9dc0125377cbf3e7acbfc71c728f659dbf0393d8df744ccb4cb4e4710de9ba` | `A` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-71522fdb53607968881c1f46300f191407cbb57faf107c677f3b1f2a8e1215ef` | `A` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-7e60e6d84007a36d0aa0c75f449d8465c4495fc4c35ef626584a9d9792e1b847` | `B` | yes | `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-82bb8a6abb410d10c001a2f87a8a6f6461e74d88c34eed3de98da6d5f630ac57` | `B` | yes | `shipping.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `refunds.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-85c29a37067aba7ba527a3867287823b7465b23d99df1e612923a0cab921ee87` | `B` | yes | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `orders.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-883781d4a9b2f0fac54c213f6dbff3657e08093b5211ad7d37426dd3d9de5c86` | `A` | yes | `shipping.flipkart_faqs.others-shipping.9b7d1ed201726532775a77e845bd84447b4c666bc1fab3e15b8a896ce8a440fe`, `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90` | `B` | yes | `returns.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-b15a91373f3c5cc0b914abf60042533cf2d59e9fa97cbe35e6be36a790ee04a3` | `B` | yes | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-bd8a4918f29d03a02fb98b5ddc98b14a1acc40c7bf7d8eb0f10163e614c87a8a` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-d7dcc979ed24d2759235a9dbe35dde58263c90b867972425fc4f168e2851a8d1` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-e076904c3f4698e321d37fb60f4735933bcc0eee89bad8e3f5e34eaed572ed99` | `A` | yes | `shipping.maktek_faqs.generic-store.5c8d1db88fb2b1a907bd1a2f6b2bc37ade7502357c8948e1c118e2ebce589b43`, `orders.maktek_faqs.generic-store.5c8d1db88fb2b1a907bd1a2f6b2bc37ade7502357c8948e1c118e2ebce589b43` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-e19f02b2acb4ae44eebeb6e37dfe28181749b05b08779a5faa44bd7a746f6e65` | `B` | yes | `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-e4646c2890d13d940b140cf400ae92767dc7fe1c2b1dfb3f50c1219fe6e54334` | `B` | yes | `returns.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-ef5f3a1c0c87efa9038a513b697f2fc8acea6534f669bed30adfbc6deee5d67d` | `B` | yes | `warranty.flipkart_faqs.order.bc6b42eb666577388fc2a1173318ade0061ff34f393ced180770628f0e429b44`, `membership.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |

## smoke-test-20261121-c80a8668-ed86add9

- Source `eval/runs/smoke-test-20261121-c80a8668-ed86add9`
- Git SHA `c80a86680e8de321580d71656fd2929a6385d127`
- Config hash `4cd25a2c4f502373923125c0bb5521e73f934afa47484840a26e5e87a4b10eaa`
- Eval file hash `9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424`
- Corpus hash `60e259f600ed4ae895106d14385edcb6cfcf12071ec0219a32a936a209c5c6fd`
- Recorded at 2026-11-21T07:18:37.800283+00:00 for split `test`
- Models `{"fast": "deepseek-flash", "main": "deepseek-flash"}`
- Dataset versions `{"bitext": "bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443", "flipkart_faqs": "NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228", "maktek_faqs": "MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240", "philips_manuals": "InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84"}`

| Outcome or observed pattern | Count |
|---|---:|
| Cross-document items | 10 |
| Accepted | 8 |
| Rejected | 2 |
| Reached knowledge retrieval | 9 |
| Reached knowledge retrieval with every gold section in the top 5 | 9 |
| Recorded gate passed | 9 |
| Rejected before knowledge retrieval | 1 |
| Rejected with exactly one gold section missing after retrieval | 0 |
| Rejected with multiple gold sections missing after retrieval | 0 |
| Rejected with a failed gate | 0 |
| Coverage marked a part unsupported | 0 |
| Coverage relied on absence | 0 |
| Invalid quote or quote source | 0 |
| Dependency unavailable | 1 |

| Item | Initial path | Reached knowledge retrieval | Gold in recorded top 5 | Gold absent from recorded top 5 | Gate | Handoff reason | Answer status and error | Accepted |
|---|---|---|---|---|---|---|---|---|
| `cross_doc-0cb34ef4afd01de7e99fcad1a039179cdea74b413a5dbba2c5e2ac6c2268ce2d` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-2f9a30ebcd3e524f0d41884fda7b9ee8ab1fd3a30fd3dbc06114abb4ed9bf680` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-4188c9824c8648bd82230802a837bdf76e4a9aec72cf806ab2dc4a22923ffde9` | `C` | no | — | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `shipping.flipkart_faqs.others-shipping.9b7d1ed201726532775a77e845bd84447b4c666bc1fab3e15b8a896ce8a440fe` | — | `order_not_found` | `not_attempted` | no |
| `cross_doc-46eb19eb0956c3e6b9422fc5952778443054088afa10f205449b9d734cecb230` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-5532f722baa093833d5d9dab02f43fe3c50b23e73482554b4ba38cadb47a7a90` | `B` | yes | `payments.flipkart_faqs.others-gift-cards.031f7b62c9b9cc45f3f0efc902093c5bd766bd45ea60e0a944e5417d010cb5ef`, `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-7e60e6d84007a36d0aa0c75f449d8465c4495fc4c35ef626584a9d9792e1b847` | `B` | yes | `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90` | `B` | yes | `returns.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | `dependency_unavailable` | `model_error`, `OpenAIConnectionError` | no |
| `cross_doc-bd8a4918f29d03a02fb98b5ddc98b14a1acc40c7bf7d8eb0f10163e614c87a8a` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-d7dcc979ed24d2759235a9dbe35dde58263c90b867972425fc4f168e2851a8d1` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-e4646c2890d13d940b140cf400ae92767dc7fe1c2b1dfb3f50c1219fe6e54334` | `B` | yes | `returns.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |

## smoke-test-20261121-b7d761af-dc9d2d85

- Source `eval/runs/smoke-test-20261121-b7d761af-dc9d2d85`
- Git SHA `b7d761af3a9ac4887ce93526f75cf4b0768a4714`
- Config hash `9fcc2aaa86717044a9f875fafbe4bccc054602b6e5c021e336ff48f28e803661`
- Eval file hash `9ed7c618bd6e57767c81da67e106a90dee701ae576ab83102d1485a9bb051424`
- Corpus hash `60e259f600ed4ae895106d14385edcb6cfcf12071ec0219a32a936a209c5c6fd`
- Recorded at 2026-11-21T08:19:26.265741+00:00 for split `test`
- Models `{"fast": "deepseek-flash", "main": "deepseek-flash"}`
- Dataset versions `{"bitext": "bitext/Bitext-customer-support-llm-chatbot-training-dataset@430d1a89bd93bd1fa23c16f29dd53e73f0087443", "flipkart_faqs": "NebulaByte/E-Commerce_FAQs@66a7c3105e6001ce7a314f113597b27a7b2e6228", "maktek_faqs": "MakTek/Customer_support_faqs_dataset@858a539411eaeb97cc2c78e3262d067abe8fa240", "philips_manuals": "InfiniFlow/Ecommerce-Customer-Service-Workflow@563e41c016e3d27a4501785e76cc0f3e6fd3fc84"}`

| Outcome or observed pattern | Count |
|---|---:|
| Cross-document items | 10 |
| Accepted | 9 |
| Rejected | 1 |
| Reached knowledge retrieval | 9 |
| Reached knowledge retrieval with every gold section in the top 5 | 9 |
| Recorded gate passed | 9 |
| Rejected before knowledge retrieval | 1 |
| Rejected with exactly one gold section missing after retrieval | 0 |
| Rejected with multiple gold sections missing after retrieval | 0 |
| Rejected with a failed gate | 0 |
| Coverage marked a part unsupported | 0 |
| Coverage relied on absence | 0 |
| Invalid quote or quote source | 0 |
| Dependency unavailable | 0 |

| Item | Initial path | Reached knowledge retrieval | Gold in recorded top 5 | Gold absent from recorded top 5 | Gate | Handoff reason | Answer status and error | Accepted |
|---|---|---|---|---|---|---|---|---|
| `cross_doc-0cb34ef4afd01de7e99fcad1a039179cdea74b413a5dbba2c5e2ac6c2268ce2d` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-2f9a30ebcd3e524f0d41884fda7b9ee8ab1fd3a30fd3dbc06114abb4ed9bf680` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-4188c9824c8648bd82230802a837bdf76e4a9aec72cf806ab2dc4a22923ffde9` | `C` | no | — | `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3`, `shipping.flipkart_faqs.others-shipping.9b7d1ed201726532775a77e845bd84447b4c666bc1fab3e15b8a896ce8a440fe` | — | `order_not_found` | `not_attempted` | no |
| `cross_doc-46eb19eb0956c3e6b9422fc5952778443054088afa10f205449b9d734cecb230` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-5532f722baa093833d5d9dab02f43fe3c50b23e73482554b4ba38cadb47a7a90` | `B` | yes | `payments.flipkart_faqs.others-gift-cards.031f7b62c9b9cc45f3f0efc902093c5bd766bd45ea60e0a944e5417d010cb5ef`, `returns.flipkart_faqs.cancellations-and-returns.9f8b556f560802090a05fde0391ff27758e799ca701ebb8538d0dc6bc82671c3` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-7e60e6d84007a36d0aa0c75f449d8465c4495fc4c35ef626584a9d9792e1b847` | `B` | yes | `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775`, `membership.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-a33e500413f4237e044f86cc3d52867d48ab1916e82f382e0d9091e0f163ba90` | `B` | yes | `returns.flipkart_faqs.flipkart-plus.3652d050d0ddb116408ff1b7de80a4c6dd5460e711735065a471434e8de3afa9`, `membership.flipkart_faqs.others-login-my-account.e39d8f2545ece44d794d6a4742d3f8405215ec5e8512f5984749a352639bddb7` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-bd8a4918f29d03a02fb98b5ddc98b14a1acc40c7bf7d8eb0f10163e614c87a8a` | `B` | yes | `payments.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `warranty.flipkart_faqs.others-warranty.4c567196a42f26ff8aa872e923e34e054944179894a8918c37eaee49ef90b775` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-d7dcc979ed24d2759235a9dbe35dde58263c90b867972425fc4f168e2851a8d1` | `B` | yes | `shipping.flipkart_faqs.payment.5391e2c83b3fb8269dfbac6a9a50634576a6a7b0f1c3fe563d3ccf298c3f3f46`, `membership.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
| `cross_doc-e4646c2890d13d940b140cf400ae92767dc7fe1c2b1dfb3f50c1219fe6e54334` | `B` | yes | `returns.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc`, `payments.flipkart_faqs.supercoins.1b5a44064b958b635438168ab3ebb185601d6cbc0116df19772b3e7c378e65fc` | — | pass (`passed`) | — | `answered` | yes |
