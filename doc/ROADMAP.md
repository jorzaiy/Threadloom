# Threadloom 演进路线：记忆 / 世界 / NPC / 关系

承接 `doc/MEMORY-V2-DESIGN.md`（V2 记忆已落地：fact-log 单一真相 + 纯投影 + 实体归并/canonical 升级 + persona 锁定 + 知情边界白名单 + narrator 接管【人物档案·权威】块）。

本文件是**下一阶段的优先级路线**。目标：**让长记忆真正可用、让世界和 NPC 活起来、让关系有据可循地成长**——同时守住一条底线：

> **结构提供锚与约束，血肉让模型演。别把 NPC 做成状态机。**

## 优先级总览

| 序 | 工作项 | 解决什么 |
|---|---|---|
| **P1 🚧** | 语义检索（词法这刀已落地） | memory 真瓶颈：长尾召回 |
| **P2 ✅** | 关系事件线（已完成） | NPC 与主角关系成长（有历史、可回溯） |
| **P3** | NPC 目标 / 议程 | 世界自主、NPC 像独立的人 |
| 缓做 | persona 演化、离场世界推进 | 高价值但易失控，谨慎晚做 |
| 贯穿 | keeper 抽取契约 | 所有方向的共同上游 / 天花板 |

每步沿用 V2 的纪律：**开关 + 影子验证 + 可回退，不大爆炸。**

---

## P1 · 语义检索 — 🚧 词法这一刀已落地（commit `df2641c` / `2d09448` / `8c11415`）

**已落地**：设计文档第三个纯函数 `retrieve()` 实装为 `backend/fact_retrieval.py`——**BM25 词法 + 实体链接 + 近窗，三车道 RRF 融合**，零新依赖。融合的是 rank 不是分数，所以之后加 embedding 车道**不用重调**前三条。双轨接入：`THREADLOOM_RETRIEVE_SHADOW`（默认开，只写 `diagnostics/retrieve_shadow.jsonl`）+ `THREADLOOM_RETRIEVE_V2`（默认关，才注入【往事回溯·检索】块）。

**实测（c701f6，93 facts / 39 轮）**：先是**比基线更差**（MRR 0.26 vs 0.87），三个坑——车道等权让近窗废话占头部、`present` 行入索引被长度归一化捧起来、实体车道被 `knows` 吃满配额；修完 **0.84**（基线 0.87），各有回归测试。

**关键结论：改写型 query 上纯词法到顶了**。`骨头/鸟骨`、`兵器/断剑`、`护身/护盾` 零 token 重叠，两种算法都召不回（基线看似第 6/18 名是"并列 0 分后按时间排"的巧合）。所以下一步价值全在 embedding 车道，而不是继续磨词法。

**embedding 的现实约束（2026-08-25 实测）**：网关只有 5 个 chat 模型、`/v1/embeddings` 无可用模型；机器上无 torch/sentence-transformers/onnxruntime/numpy/llama.cpp/gguf。onnxruntime 可装（x86_64 + glibc 2.36 + py3.11 命中 manylinux_2_28 轮子，AVX-512/VNNI 齐全），代价是 requirements 从 5 行涨到 ~7 行 + ~110MB 模型 + 3.7GB 内存里只剩 ~1.5GB 可用；且得先 `apt install python3.11-venv`（`.venv-jieba` 是空壳就是因为这个）。

**待做**：① 手标召回基准集（20-30 条，**必须含改写型 query**，否则量出来的是词法自己的强项）；② recall@k / MRR 跑分脚本 + "默认开"的门槛；③ embedding 车道 + 向量缓存（纯投影、可删可重建）；④ 顺带收割：用同一套向量喂 auditor 的归并候选（治 掌柜/周掌柜、面摊老板/摊主、灰衣/灰布衫）。

**原始判断（保留）**：长尾前情"用时取回"是 memory 的真瓶颈，不是存储。检索 = 近窗 + 在场实体的 fact + 语义命中 observation，**每条带 span 回源**；预算仍由 `context_builder` 决定。

## P2 · 关系事件线 — ✅ 已完成（commit `91f59c8` / `b959714`）

**已落地**：`relation` fact（关系 label 变才追加、带 evidence + span + 去箭头规范化）→ `project()` 投影 `entity_relationship`（当前=最新、**动态不锁**）+ `entity_relationship_history`（带 turn/why 的关系线）→ 权威块展示"对主角=<关系>（依据）"并声明关系是动态、会演变。b93051 验证：沈昭 `戒备 → 初步信任 → 初识 → 相知`。剩 label 阶段乱序（如阶段回退）属 keeper 噪声、归 keeper 契约。

**目标**：NPC 与主角的关系**有历史、可回溯、可引用**地成长，而不是单一标签突变。

**现状**：relationship 是线上单一标签（戒备/同伴），粗、变化突兀。

**做法**：
- fact-log 记 `relation` fact（subject=NPC、object=主角、label、**带 span**：第 X 轮何事改变了关系）；
- "当前关系" = 这些 relation fact 的**投影**（动态、不锁——正合"随剧情变、不写死"）；
- 权威块/narrator 输入展示当前关系 + 可引用的关键关系事件（"上次你救过他"）。

**接现有**：`relation` 谓词在 fact-log 设计里早留了位，未实装。让关系成长有据可循，NPC 也记得你们的过往、互动有连续性。

## P3 · NPC 目标 / 议程

**目标**：世界"自主"、NPC 像独立的人——主动推进自己的事，不只是回应主角。

**做法**：
- fact-log 给重要 NPC 记一条"当前目标/想要什么"（`goal`，带 span，可随剧情更新）；
- narrator 据此让 NPC 主动行动；arbiter 可提示"按其目标/persona 该如何反应"。

**取舍**：目标要是**倾向**、不是脚本——太刚性 NPC 就像执行批处理。

## 缓做（高价值但易失控）

- **persona 演化**：persona 默认锁定（已做），仅"重大事件"触发**一次**性格修正（append 带 span，不每轮漂），由 keeper/arbiter 判定"重大"。
- **离场世界推进**："这段时间发生了什么"——诱人但易脑补（参见 deepseek 的脑补倾向）。必须基于已登记的 thread/目标推、绝不凭空编；晚做。

## 贯穿上游 · keeper 抽取契约

fact-log 是 keeper 的下游，**keeper 标得准不准是所有方向的天花板**。已观察脆点：keeper 没标别名（"短工"没并进"桥上探头男人"）、knowledge 把场景观察当 NPC learned、grok 命名泛滥。

→ 专门投入"让 keeper 更准地标 **实体 / 别名 / 关系事件 / NPC 目标**"，比下游任何单点优化都更普惠。

**进度**：
- ✅ 临时 NPC 治理（fact-log 确定性侧，commit `8d34b69`）：恰好在场一次、离场≥2 轮的路人不进长期账本（important/权威块），实体仍留表；present==1 only，seed/仅被提及的 absent NPC 豁免。
- ✅ knowledge 内容质量（keeper prompt 契约，commit `80cf610`）：knowledge_scope 只记真·知情（主角身份/意图/秘密、剧情、关系），不掺环境/场景/动作观察。
- ✅ 别名标注（keeper prompt 契约 + fact-log 消费测试，本次）：同一人本轮换称呼时把别称标进 scene_entity `aliases`，fact-log 据此归并（治"短工"只在正文出现的情况）。
- ✅ NPC 知情边界正文守卫（narrator 拒收 + keeper `immediate_goal` 私下告知校验，commit `ff3eb04`）：在场 NPC 不得回应主角没说出口的话、或泄露其私下探查（贴符/夜探/路线/内心推演）；命中触发定向 retry，keeper 侧拒收会逼主角当面坦白的目标。属正文层守卫，效果取决于模型、需真实游玩验证（narrator/keeper 消费侧已有测试）。
- ✅ 远程/回忆提及不重置在场名单（keeper partial-accept，commit `5b65c54`）：`_name_has_current_text_evidence` 排除只在回忆/画外音里出现的名字，路人不再被重新拉回 onstage。
- 待做：relation label 规范（去箭头已做，防阶段无理回退）。注：knowledge / 别名两条是 **prompt 契约**，效果取决于模型、需真实游玩验证（fact-log 消费侧已有测试覆盖）。

## 贯穿原则

- **别做成状态机**：persona 锁太死、关系太机械、目标太刚性 = NPC 在填表。结构是锚，血肉让模型演。
- **省 LLM / 本地优先**：embedding 走便宜档；重活（提炼、推进）放离线/consolidation，不进每轮热路径。
- **可回退**：开关 + 影子 + 渐进，每步独立见效。
