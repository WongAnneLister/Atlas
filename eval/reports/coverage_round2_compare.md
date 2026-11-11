# End-to-end run comparison

- Run A Git SHA: `5da6301e9b80487c248e211a7fce535c8ffc31eb`
- Run A config hash: `7aa735a01dfeaa3c3b419d3c433f1da05cd30b60361e80fc0cb5433dfdf4f845`
- Run A eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Run A split/date: test / 2026-11-11T13:55:20.301829+00:00
- Run A models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Run B Git SHA: `56cdc00b0a292a3a8c36a2b66cab573fb307989c`
- Run B config hash: `7aa735a01dfeaa3c3b419d3c433f1da05cd30b60361e80fc0cb5433dfdf4f845`
- Run B eval file hash: `fe82c904801b17c7ba8162f01f4d8807c9ee7a3fba3c8c01f341429e17202cf9`
- Run B split/date: test / 2026-11-11T15:35:19.957222+00:00
- Run B models: `{'fast': 'deepseek-flash', 'main': 'deepseek-flash'}`
- Shared items: 150
- Only in A: 0
- Only in B: 0

## Metric deltas (B minus A)

| Metric | A | B | Delta |
|---|---:|---:|---:|
| False Accept | 3.33% | 0.00% | -3.33% |
| False Reject | 8.33% | 9.17% | +0.83% |
| Pass Rate | 74.00% | 72.67% | -1.33% |

| Item | Accepted A | Accepted B | Handoff A | Handoff B |
|---|---:|---:|---|---|
| basic_policy-00da093dcecaa1f75c5c1496568921b0d676134207db47edcda896e3158ad011 | False | True | None | None |
| basic_policy-621dcf09c082cf6376772077b5a0da3f0fabe420ce1cc947c37ea09c7a5144e9 | True | False | None | order_not_found |
| colloquial-1cc997ef957e8e28d10ee652483326f042a8a72e95ed28755921a47bf8899a83 | True | False | None | incomplete_evidence |
| colloquial-2c01e1cd08b21ff081642afa3b3ab5ff37e893bce1a324f6da019f123739b672 | True | False | None | incomplete_evidence |
| colloquial-57f3919c97c128b684c2739ae7d69a015f46816491276ef949e3d76e328d0bd3 | True | False | None | incomplete_evidence |
| colloquial-936394a4d078a888a3ad1931489aef79fe801dbda3f06f206fba0a0bfd0ff04a | True | False | None | incomplete_evidence |
| colloquial-a9a724c1cf62d70f383d9fb3bf3cf3b2ac647f3cb4ee37137580e574ca34c644 | True | False | None | incomplete_evidence |
| colloquial-b625edc0cace123506168d5e96a5b80408dc3561671caa8ffe4d11006def0ccc | False | True | None | None |
| colloquial-be04851050d42e218fc4a91af51ac75ac54d17334f3c8d76b8722f839e131e65 | True | False | None | incomplete_evidence |
| colloquial-ea2731aee6569d73cf416c66850fbbbb51ff9dbcd7ee9c81a03edf3e704922f2 | True | False | None | incomplete_evidence |
| cross_doc-0cb34ef4afd01de7e99fcad1a039179cdea74b413a5dbba2c5e2ac6c2268ce2d | False | True | low_evidence | None |
| cross_doc-1a3b877478fe5a7e257e5d84a1ea9eeec3b1bb57d49f07d7043167a9e395cfa2 | False | True | low_evidence | None |
| cross_doc-2f9a30ebcd3e524f0d41884fda7b9ee8ab1fd3a30fd3dbc06114abb4ed9bf680 | False | True | low_evidence | None |
| cross_doc-3312b6e8ecf5d4916a41cbf391aefdf4d6f0715b41c76d9a89118862e31be765 | False | True | None | None |
| cross_doc-49c59ca41d465ad30467f2eba03222fa4fa6e7a19cfe125f1e1d24c6764e582e | True | False | None | incomplete_evidence |
| model_number-aeee8a08abe8738816bc1e336e4cf45634ae40b25594bab52e196e289d3f96ff | False | True | None | None |
| model_number-b9cbda214fe23748e480975624d285acf93860ade827d14bd62a7f77576a4f3f | False | True | None | None |
| no_answer-bf6b69c20457ff8d9cfefaae4f425a4392b2125a76cfb63ae20c1fccaa7b534f | True | False | None | incomplete_evidence |
