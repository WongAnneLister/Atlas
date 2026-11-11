# End-to-end run comparison

- Run A Git SHA: `9ed1d576deca7c52494a51d728cc06a63d365815`
- Run A config hash: `7aa735a01dfeaa3c3b419d3c433f1da05cd30b60361e80fc0cb5433dfdf4f845`
- Run A eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Run A split/date: test / 2026-11-10T15:11:06.756261+00:00
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B Git SHA: `5da6301e9b80487c248e211a7fce535c8ffc31eb`
- Run B config hash: `7aa735a01dfeaa3c3b419d3c433f1da05cd30b60361e80fc0cb5433dfdf4f845`
- Run B eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Run B split/date: test / 2026-11-11T13:55:20.301829+00:00
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | A | B | Delta |
|---|---:|---:|---:|
| False Accept | 3.33% | 3.33% | +0.00% |
| False Reject | 26.67% | 8.33% | -18.33% |
| Pass Rate | 59.33% | 74.00% | +14.67% |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-00da093dcecaa1f75c5c1496568921b0d676134207db47edcda896e3158ad011 | True | False | None | None |
| basic_policy-050ca03687ccfd011f415d4d991357c98f1d1a921acf0d561c068fcd1fc0eddf | False | True | order_not_found | None |
| basic_policy-33fbfa418b9ed1d9afc7da5065123ec69d208e12ac82618b9fa89505e3cbce24 | False | True | None | None |
| basic_policy-507bd158070ca7ca00dd41778b65db820ee600ce9d05517827b40ef5adcdecd2 | False | True | tool_error | None |
| basic_policy-621dcf09c082cf6376772077b5a0da3f0fabe420ce1cc947c37ea09c7a5144e9 | False | True | order_not_found | None |
| basic_policy-80096acc793f43d74d8bd0ae24bd6fbb361e691f596ceda4b79370db763e62e0 | False | True | None | None |
| basic_policy-85bbdb32a68244216f31daa2c571c8da165e4f1a0df6d65364473329601b9b52 | False | True | None | None |
| basic_policy-9bae78d4f19638095dc1f5a6704a12c796058e7f84012d06dda2eec70664c28e | False | True | tool_error | None |
| basic_policy-b59ede0c47cb3bf273b7df98fd859557c7d3cc9b879d88c765f91eeae4f1aab2 | False | True | None | None |
| basic_policy-ea4182a11f166da24d06c4b1134c4d40e0ae136ebc8d9f46b660efda1a132416 | False | True | None | None |
| colloquial-172c423884d2eec0e420fadfd8eecb9a466fab6d2e47bb1aafa599a052939eb2 | False | True | None | None |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | False | True | None | None |
| colloquial-2c01e1cd08b21ff081642afa3b3ab5ff37e893bce1a324f6da019f123739b672 | False | True | tool_error | None |
| colloquial-3294949dbbccc9093dccf23113c550458655b37b50262c68b0ded1b2bae4c400 | False | True | None | None |
| colloquial-57f3919c97c128b684c2739ae7d69a015f46816491276ef949e3d76e328d0bd3 | False | True | None | None |
| colloquial-9168c68be1e51f1579ddee743b9b9e7af98f87365a00153db97fe6c009f4e8c8 | False | True | None | None |
| colloquial-9d1dd1e1d65a8b5eddab4538175df149e2d917fdce73e0353f62be03f4c81e42 | False | True | tool_error | None |
| colloquial-a9a724c1cf62d70f383d9fb3bf3cf3b2ac647f3cb4ee37137580e574ca34c644 | False | True | None | None |
| colloquial-b625edc0cace123506168d5e96a5b80408dc3561671caa8ffe4d11006def0ccc | True | False | None | None |
| colloquial-be04851050d42e218fc4a91af51ac75ac54d17334f3c8d76b8722f839e131e65 | False | True | tool_error | None |
| colloquial-d49849e80d3226360462d7864cc208e3ad3bad67b726d45fcc888985fa492dfa | False | True | tool_error | None |
| colloquial-e740e5eb769e4a444777088b0fde717f2bb168e99d30dc179eb665cd299b6843 | False | True | order_not_found | None |
| colloquial-ea2731aee6569d73cf416c66850fbbbb51ff9dbcd7ee9c81a03edf3e704922f2 | False | True | None | None |
| colloquial-f6f6dae584fc8096bb9d7d4a65f46c055913e248826da762d31d5f76f274cdde | False | True | tool_error | None |
| cross_doc-0cb34ef4afd01de7e99fcad1a039179cdea74b413a5dbba2c5e2ac6c2268ce2d | False | False | None | low_evidence |
| cross_doc-1a3b877478fe5a7e257e5d84a1ea9eeec3b1bb57d49f07d7043167a9e395cfa2 | True | False | None | low_evidence |
| cross_doc-2f9a30ebcd3e524f0d41884fda7b9ee8ab1fd3a30fd3dbc06114abb4ed9bf680 | True | False | None | low_evidence |
| cross_doc-3312b6e8ecf5d4916a41cbf391aefdf4d6f0715b41c76d9a89118862e31be765 | True | False | None | None |
| cross_doc-45ddcc1faa1d0778b2ad98c5a860265156573d965fc3e405f3f4cd562198285b | False | True | None | None |
| cross_doc-5b9dc0125377cbf3e7acbfc71c728f659dbf0393d8df744ccb4cb4e4710de9ba | False | True | tool_error | None |
| cross_doc-883781d4a9b2f0fac54c213f6dbff3657e08093b5211ad7d37426dd3d9de5c86 | False | True | tool_error | None |
| model_number-6d0751859e86c9eba07dae4953b59066bec718ad7c792bd06d98d36a93e6fe2c | False | True | low_evidence | None |
| model_number-7dba0d6c3bab91d6eb1322b498492f2ebca22629b2aa6e0d521c90604687b045 | False | True | None | None |
| model_number-9dfbaf89a7491e6e55d5004cbed910da121c0aa1c21800021eb7627a7bd8ca30 | False | True | low_evidence | None |
| model_number-a3d5bd0c01cf309c453ac41d6a6cca01edae012003ceaf2598a5c14ddd078cda | False | True | low_evidence | None |
| model_number-aeee8a08abe8738816bc1e336e4cf45634ae40b25594bab52e196e289d3f96ff | True | False | None | None |
| model_number-b9cbda214fe23748e480975624d285acf93860ade827d14bd62a7f77576a4f3f | True | False | None | None |
| no_answer-03c1d6a5569ebc834065481b8478437ae1e83b0e048f5a5717a013a553e65b9a | False | False | tool_error | low_evidence |
| no_answer-243904253eb36c25ebd69406f6dbdea2ea52c3cd0bc9bdcda94cae25c2c02421 | False | False | None | low_evidence |
| no_answer-3485f92cf2bc51d70e198908421c5192ddd8502097fed04bd6a5b266ae5f3d58 | False | False | None | low_evidence |
| no_answer-535874b14d567bd6986c60361a9f10c27c3b155eb1cfbaaa9c60d81ef2690aae | False | False | None | low_evidence |
| no_answer-6944c2623b572b0d92ab1243194bafcba8dfd1897439f33f54dd48c32bdd9e01 | False | False | None | low_evidence |
| no_answer-8ee6d815f4924acc3ce0458803e7503a10b2a496fb355e68f9911fa20dae4bb5 | False | False | None | low_evidence |
| no_answer-9d2db708c5b61d98fcc8a8ddc7dee416a8c2591e475802ae4fa8fdceb6ba75a3 | False | False | tool_error | low_evidence |
| no_answer-9fefb0f9aea97d43d42072a03fc9b83b57b60f7d0c4dd090eab3eec1283c175d | False | False | None | low_evidence |
| no_answer-a7df1a82131af9d360054aa05512f30a4ec0a7c97906ea628c4b6bf1cd416ea1 | False | False | None | low_evidence |
| no_answer-d46ba4779cca80b5aa6d961256b1ec4cf225e00d4bda58bb834cb6dc20f9c541 | False | False | None | low_evidence |
| no_answer-db23ddea63f091d2c3032a4286b1af9ff7d4641159c3e51b9f7bd50a642cfa7e | False | False | None | low_evidence |
| no_answer-fd715913ea428d4089aafb3d14c612fe9fc78e178333a0a962e05b08fab872ca | False | False | None | low_evidence |
