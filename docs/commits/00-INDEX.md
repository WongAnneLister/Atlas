# 提交计划总览（35 个 commit，分两期）

每个 commit 对应一个提示词文件。用法：

1. 新开一个 Claude Code / Codex 会话，工作目录是项目根目录。
2. 把对应的 `NN-xxx.md` **整篇**粘进去（或者说：`Read docs/commits/NN-xxx.md and do it`）。
3. 等它跑完 `make check` 并提交，**你自己看一遍 diff、`docs/PROGRESS.md` 和它写的面试笔记**，再开下一个。
4. 一个会话只做一个 commit，上下文干净，出错也好回滚。

提示词全是英文（仓库是英文的，Agent 读英文也更稳）。每篇固定结构：
Context → Read first → Task → Requirements → Tests → Out of scope → Done when → Commit message。

## 顺序和检查点

| # | 文件 | 做什么 | 周 | 依赖 |
|---|---|---|---|---|
| 01 | [01-scaffold.md](01-scaffold.md) | 项目骨架、配置、Makefile、Docker、CI | 1 | — |
| 02 | [02-data-download.md](02-data-download.md) | 下载三个数据集 + 许可证报告 | 1 | 01 |
| 03 | [03-policy-docs.md](03-policy-docs.md) | FAQ 合并成政策长文档 + 商品目录 | 1 | 02 |
| 04 | [04-mock-orders.md](04-mock-orders.md) | 假订单库 + OrderService | 1 | 01 |
| ✅ | **检查点 1** | 文档和 mock 数据就绪 | | |
| 05 | [05-eval-set.md](05-eval-set.md) | 300 题评估集 + 校验脚本（**先于检索**） | 2 | 03 |
| 06 | [06-chunking-ingest.md](06-chunking-ingest.md) | 切分 + BGE-M3 + 写入 Milvus | 2 | 03 |
| 07 | [07-hybrid-retrieval.md](07-hybrid-retrieval.md) | 向量 + BM25 + RRF | 2 | 06 |
| 08 | [08-rerank-retrieval-eval.md](08-rerank-retrieval-eval.md) | 重排 + 四种配置对比报告 | 2 | 05, 07 |
| ✅ | **检查点 2** | 4 种检索配置都测完 | | |
| 09 | [09-graph-intents.md](09-graph-intents.md) | LangGraph 骨架、改写、9 意图分类 + 准确率 | 3 | 01 |
| 10 | [10-tool-paths.md](10-tool-paths.md) | 订单/物流工具路径、投诉、闲聊 | 3 | 04, 09 |
| 11 | [11-evidence-gate.md](11-evidence-gate.md) | 证据门控 + 带引用回答 + 转人工 | 3 | 08, 09 |
| 12 | [12-refund-flow.md](12-refund-flow.md) | 退款子流程（interrupt / resume） | 3 | 10, 11 |
| 13 | [13-e2e-eval-sweep.md](13-e2e-eval-sweep.md) | 端到端评估 + 阈值扫描 + 幻觉评审 | 3 | 11, 12 |
| ✅ | **检查点 3** | 库外题误放率 = 0% | | |
| 14 | [14-api-sse-ui.md](14-api-sse-ui.md) | FastAPI + SSE + 聊天页 | 4 | 12 |
| 15 | [15-langfuse-cost.md](15-langfuse-cost.md) | Langfuse 追踪 + 按意图算成本 | 4 | 13 |
| 16 | [16-readme-demo.md](16-readme-demo.md) | 英文 README + 演示脚本 | 4 | 全部 |
| ✅ | **检查点 4** | 仓库公开 + 演示视频 | | |

可以并行的：04 和 02/03 互不依赖；09 只依赖 01，可以和第 2 周的检索并行做。

**第一期（01–16，4 周）先做完、先上线、先拿去投简历。** 第二期边投边做，面试时可以说“正在做”。

## 第二期：生产级（第 5–12 周，v1 上线并开始投简历之后再做）

原则：**每个功能先写评估，再写功能，最后出带置信区间的前后对比报告。** 详见 AGENTS.md §5.7。

| # | 文件 | 做什么 | 方向 | 依赖 |
|---|---|---|---|---|
| 17 | [17-eval-platform-ci.md](17-eval-platform-ci.md) | 评估平台：数据集版本、置信区间、裁判校准、CI 发布门禁 | 评估 | 16 |
| 18 | [18-postgres-redis.md](18-postgres-redis.md) | Postgres + Redis，持久化 checkpoint，迁移 | 平台 | 17 |
| 19 | [19-reliability.md](19-reliability.md) | 超时/重试/降级/熔断，依赖挂了就转人工，幂等，并发锁，指标 | 平台 | 18 |
| 20 | [20-redteam-set.md](20-redteam-set.md) | 红队测试集（先测基线，不修） | 评估 | 17 |
| 21 | [21-guardrails-security.md](21-guardrails-security.md) | 护栏、PII 脱敏、鉴权、限流，红队前后对比 | 平台 | 19, 20 |
| 22 | [22-incremental-ingestion.md](22-incremental-ingestion.md) | 增量入库、索引版本、过评估才切换别名、可回滚 | RAG | 17, 18 |
| 23 | [23-policy-versions-metadata.md](23-policy-versions-metadata.md) | 政策按日期生效（按下单日判断退款）、元数据过滤 | RAG | 22 |
| 24 | [24-query-planning.md](24-query-planning.md) | 复杂问题拆分、每部分单独门控、部分回答 | RAG | 17, 23 |
| 25 | [25-claim-grounding.md](25-claim-grounding.md) | 生成后逐句核对引用，删掉没依据的句子 | RAG | 17, 24 |
| 26 | [26-caching.md](26-caching.md) | 三层缓存，保证不过期、不串用户 | RAG | 22, 23, 25 |
| 27 | [27-multiturn-sim-trajectory.md](27-multiturn-sim-trajectory.md) | 多轮用户模拟器 + 60 个场景 + 轨迹指标（先测基线） | 评估 | 17, 21 |
| 28 | [28-context-builder.md](28-context-builder.md) | ContextBuilder：按稳定性分层（L0–L4）、按节点分配 token 预算、适配各家缓存断点、前缀稳定性测试 | 上下文 | 27 |
| 29 | [29-short-term-memory.md](29-short-term-memory.md) | 短期记忆：分段压缩成冻结的摘要块（不每轮重写）+ 钉住的事实（支持改口） | 记忆 | 28 |
| 35 | [35-prefix-cache-experiment.md](35-prefix-cache-experiment.md) | **紧接 29 做**：滑窗 / 滚动摘要 / 分段压缩 / 不开缓存 四组对比 + 可选 vLLM KV 层测试 | 上下文 | 29 |
| 30 | [30-long-term-memory.md](30-long-term-memory.md) | 长期客户记忆：写入策略、过期、用户可删、防串号；会话内冻结在 L1 | 记忆 | 18, 21, 29, 35 |
| 31 | [31-handoff-loop.md](31-handoff-loop.md) | 转人工队列 + 客服后台 + 结案标签回流成评估题和文档缺口 | Agent | 18, 19, 30 |
| 32 | [32-online-eval-drift.md](32-online-eval-drift.md) | 线上评估：点赞点踩、抽样复核、漂移监控 | 评估 | 15, 17, 31 |
| 33 | [33-load-test-slo.md](33-load-test-slo.md) | SLO、压测、先 profile 再优化瓶颈 | 运维 | 19, 26, 28 |
| 34 | [34-deploy-readme-v2.md](34-deploy-readme-v2.md) | 公网部署 + 花费上限 + 发布流程 + README v2 | 运维 | 全部 |
| ✅ | **检查点 5** | v2 上线 | | |

按你专攻的四块看：

- **RAG**：22–26，再加 08、11 里的混合检索和门控
- **上下文管理**：28（缓存友好的上下文组装）、35（用实验证明它真的省钱又不掉质量），是整个项目最能体现“上下文工程”的部分
- **记忆**：29（会话内）、30（跨会话）
- **评估**：17、20、27、32，再加第一期的 05、08、13

为什么第二期按“评估平台 → 平台 → 安全 → RAG → 多轮评估 → 上下文 → 记忆”这个顺序：后面每一步都要用 17 的置信区间和门禁来证明“真的变好了”；28–30 要靠 27 的多轮模拟器才测得出来；30 的长期记忆要用 18 的 Postgres 和 21 的防泄漏。35 编号靠后只是因为后加的，执行顺序是 28 → 29 → 35 → 30。

## 面试笔记流水线（每个 commit 自动生成）

AI 每做完一个 commit，必须用**简单英文**回答 5 个问题，写进 `docs/notes/NN-xxx.md`，和代码一起提交，并在最后一条消息里贴给你：

1. **What**：这个 commit 做了什么
2. **Why**：为什么要做，不做会坏在哪
3. **Number**：跑出来的数字，必须写来源报告路径；还没有数字就写 "No number yet"
4. **Trade-off**：放弃了什么，代价是什么
5. **Likely follow-up question**：面试官最可能追问的一个问题，加上回答

格式和规则见 [docs/notes/TEMPLATE.md](../notes/TEMPLATE.md)：每句不超过 15 个词、一句只讲一件事、用常见词、第一次出现的术语要解释、用 "I built…" 的口吻、不编数字、没达标就照实说。

自动检查（commit 01 会建好，`make check` 里也会跑）：

- `make notes-check`：5 个标题齐全；每句不超过 15 个词；没有 leverage / robust 这类空话；**Number 里的每个数字都必须在引用的报告里找得到**；PROGRESS 里标了 done 的 commit 必须有笔记
- `make notes`：把全部笔记合成一份 `docs/INTERVIEW_NOTES.md`，面试前看这一份就够了

两个 Claude Code 斜杠命令（在 `.claude/commands/` 里）：

- `/interview-note 08`：重写某个 commit 的笔记，比如数字更新以后
- `/drill 11`：让 AI 当面试官，围绕这个 commit 一次问你一个问题，连问 5 个；每题点评，再给一个简单英文的更好版本，最后告诉你哪两处最弱

**建议用法：** 每做完一个 commit，先读一遍笔记，再跑一次 `/drill`，用嘴答，不要看。笔记是 AI 写的初稿，你要改成自己说得顺的话。

## 我替 PRD 待定问题先定的默认值（都能在 config 里改）

- **大模型**：不写死厂商，用 `init_chat_model`，分 `fast`（改写、意图、裁判初筛）和 `main`（回答）两个角色，`.env` 里填。
- **许可证**：commit 02 自动生成 `docs/LICENSES.md`，不允许再分发的数据只放下载脚本。
- **聊天界面**：FastAPI 自带一个静态 HTML 页，不搞前端工程。
- **演示**：先录视频，部署以后再说。

## 比 PRD 多加的一条（面试很加分）

评估集每类 60 题拆成 **30 dev + 30 test**：阈值和权重只在 dev 上调，结果在 test 上报。
面试官问“你阈值是不是在测试集上调出来的？”时，你可以说 *“No. I tuned on the dev split and reported on a held-out test split.”*

## 你每个 commit 后要自己检查的三件事

1. `make check` 是绿的。
2. `docs/PROGRESS.md` 更新了，数字后面写了报告路径。
3. diff 里没有 `data/raw/`、`.env`、`.sqlite`、模型权重。
