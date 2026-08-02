# Threadloom 记忆 V2 设计：单一事实日志 + 三个纯函数

**日期**：2026-06-10
**取代**：`doc/NARRATIVE-GRAPH-CODEGRAPH.md` 的 5 阶段路线（保留它的 source_span/provenance 思想，丢弃 14 类节点/14 类边的本体论和"只读缓存"定位）
**红队依据**：见下方"实测前提"。结论是否掉了"翻转真相层"的大改，改走加法式、**更少步骤**的演进。

---

## 一条原则

> **只有一个 append-only 事实日志是真相；其余一切都是它的纯函数。没有任何被多个阶段反复改写的共享可变状态。**

旧系统的病根不是某个 bug，是**形态**：narrator → keeper → `normalize_state_dict`（2500+ 行）→ important_npc_tracker → actor_registry → continuity_resolver → thread_tracker → arbiter → … 十几个阶段**轮流读写同一份 `state.json`**。P1 是 clobber loop 覆盖了 tracker 写的值；P2/P3 是四套实体命名空间各自维护、互相漂移。**只要还有共享可变状态，阶段之间就会来回污染——这是结构决定的，修不完。**

V2 把它压成三个纯函数，没有中间可变态。

---

## 实测前提（红队）

- 276 轮全量重建 = **~45ms**，memory 目录 **2.6M**，事实量小（28 实体 / 67 知情 / 17 物件 / 276 个 turn-span）。→ **投影可以每轮重算，不必缓存**，于是没有缓存失效、没有 manifest/hash/stale 那套机制。
- **29 个后端模块**读 `state.json` 核心字段。→ 迁移**不能**改这 29 个消费者；投影必须渲染出它们已经在读的 `state.json` 形状。
- 今天 keeper 是非确定 LLM，state 不是历史的纯函数（所以才 checkpoint 快照）。→ V2 把 **keeper 每轮产出本身**作为不可变事实提交，投影才成为纯函数。
- 无任何向量设施，selector 是纯词法 bigram 重叠。→ 语义召回是从 0 起的新能力，但杠杆最大。

---

## 整个系统 = 1 日志 + 1 实体表 + 3 函数

### 数据模型（刻意最小）

```text
entities                      # 唯一的实体表，取代 actors/scene_entities/important_npcs/knowledge_scope 四套 key
  id            TEXT PK        # 稳定 id，只在 commit 时分配一次
  kind          TEXT          # person | object | place
  canonical     TEXT
  aliases       TEXT[]

facts                         # 唯一的真相，只增不改
  id            INTEGER PK     # 单调递增
  turn          INTEGER        # 哪一轮产生（回滚靠它截断）
  predicate     TEXT           # present | holds | knows | relation | observation
  subject       TEXT           # entity id
  object        TEXT NULL      # entity id（relation/holds 用）
  value         TEXT NULL      # location/label/info 等
  text          TEXT NULL      # observation 的原文/细节（无损存放点）
  beat          INTEGER        # observation 是否当前节拍（main_event 的来源）
  span          TEXT           # 来源：turn_id + excerpt（provenance，沿用 graph doc）
  supersedes    INTEGER NULL   # 纠错用——append 一条新 fact 指向旧的，而不是改旧的
```

只有 **4 个结构化谓词** + **1 个 observation 兜底**。`observation.text` 就是细节的无损落点——那条"触手有暗红纹路会渗黏液"作为一条 observation 永久在册、带回源指针，靠检索按需取回。**不再有 14 类节点。**

### 三个函数（一整轮就这三步）

```python
commit(turn_prose) -> [Fact]      # 唯一的写：把本轮 prose 抽成 fact-delta，提交即不可变
project(facts<=N)  -> StateView   # 唯一的读态：纯 fold，渲染成现有 state.json 形状
retrieve(facts, q) -> Context     # 唯一的召回：近窗 + 在场实体的事实 + 语义/词法命中，带预算
```

- **commit**＝原 keeper，但契约缩小：只吐"本轮发生了什么"的 delta（含实体解析 + span），**verbatim 入库**。不再有 partial-accept / fragment-baseline / corrective-retry 那套防崩塌机制——因为没有"整张 state"可崩，单条坏 fact 被几百条稀释，且可 supersede。
- **project**＝取代 `normalize_state_dict` 的 clobber loop、important_npc_tracker、continuity_resolver、thread_tracker 的状态维护部分。`onstage_npcs`、`important_npcs`、`entity.last_event`、"某 NPC 知道什么" **全是对 facts 的查询，不是被维护的字段**。→ **P1（覆盖）在这个模型里无法表达**：`last_event` = "最近一条提到该实体的 beat fact"，是算出来的，没有可被覆盖的存储位。
- **retrieve**＝取代 selector + 各种 evidence pack 拼装。一次查询出结果，每条带 span。

---

## 旧问题在 V2 里的下场

| 问题 | V2 |
|---|---|
| P1 覆盖 | 不可表达——`last_event` 是查询 |
| P2 实体重复 | 一张 entities 表，id 只在 commit 分配一次；解析只有一处 |
| P3 知情碎片 + 裸 `npc_003` | `knows` fact 挂在 entity id 上，没有平行 label-key |
| 回滚/regenerate | `facts.delete(turn>N)` + 重 fold（45ms），比恢复快照更干净 |
| keeper 抽坏一格 | 一条坏 fact，被稀释 + 可 supersede，不再塌方 |
| 细节永久丢失 | observation.text 无损在册 + span 回源，按需 retrieve |
| 缓存污染 | **没有派生缓存**（投影每轮重算） |

---

## 删除清单（"更简洁"的实证）

V2 落地后**删掉**：clobber loop、`important_npc_tracker.py`、`continuity_resolver.py`、`scene_entities`/`important_npcs`/`knowledge_scope` 三套平行命名空间、keeper 的 fragment-baseline/partial-accept/corrective-retry 防御层、`_current_turn_onstage_npcs` 恢复、generic-anchor 各种 guard、manifest/hash/stale 缓存失效机制。
**保留**：history.jsonl（它本就是 append-only 脊梁）、source_span 思想、turn-trace（回滚证据）。

---

## 唯一的诚实难点：no-LLM 下的实体解析（commit 里那一步）

这是 P2/P3 真正死掉的地方，也是唯一不能手挥过去的。**一个 resolver 函数**，在 commit 时把每个提到的名字解析到 entity：

1. 精确名/别名命中 → 复用。
2. 归一化 key 命中（去「的/子/儿」结构助词 + 一张小同义词表，衣↔布衫）→ 复用。
3. 都不中 → **新建**（宁可新建，不做低置信度的模糊合并——模糊合并正是污染源）。
4. 没把握的近似，**不在热路径合并**，交给已经自动跑的 auditor 报告，人工或离线 supersede。

关键：因为实体只在这一处诞生，**修它就是全局修好**，不像今天散在四个文件里。

---

## 迁移：3 步，消费者一行不改

绞杀式（strangler），尊重 29 个消费者：

1. **影子**：加 facts 日志 + commit + project（渲染成今天的 `state.json` 形状），与现有管线并行跑，**diff 投影 vs 现 state** 验证一致。线上行为不变。
2. **切换**：project 成为 `state.json` 的唯一写入者，旧的十几个 reconciliation 阶段停写、删除。**消费者照旧读 `state.json`（现在由 facts 渲染），但再也改不动它——污染从这步起消失。**
3. **简化读**：把 selector 管线换成单个 `retrieve()`，补语义召回。

每步可单独上线、单独回滚。

---

## 风险（诚实）

- **commit 是单点**：prose→fact 的质量上限由它定。缓解：它是**一处**、有 span 可审、错了能 supersede——比今天 15 处互相打架可控得多。
- **语义召回从 0 起**：要引入本地 embedding（与"无 LLM 生成"不冲突，embedding 是另一档）；过渡期用"词法 + 实体链接"兜底，不阻塞前两步。
- **influence/beat 的判定**：哪条 observation 算 beat 会影响 main_event 投影。缓解：beat 由 commit 显式标记，错了是一条 fact 的事，不连累全局。
- **影子期双轨**：步骤 1 短期内两套并存，但只读不写真相，diff 收敛即切，不长期共存。

---

## 第一刀（最小）

只做迁移步骤 1 的最小切片：`backend/fact_log.py`（facts/entities schema + commit 的确定性骨架）+ `project()` 只渲染 `onstage_npcs / important_npcs / 每实体 last_event` 三个字段 + 一个测试：拿 e23032 现有 history 重放，diff 投影出的这三个字段 vs 现 `state.json`。**先证明"投影能复刻现状"，再谈替换。**

---

## 实施状态（2026-06-10，分支 `memory-v2`，未并入 master）

**已落地**：

- **slice 1 · `backend/fact_log.py`** — `Resolver`（只并语法助词「的/地/得」，偏欠并：append-only 下过并难撤、欠并易补）+ `FactLog.commit_turn / seed_from_state / truncate_after / project` + `save/load`（`facts.jsonl` + `entities.json`）。`project()` 纯折叠出 `onstage_npcs / important_npcs / 每实体 last_event`；`last_event` 是查询而非存储字段，**结构上消除了 last_main_event 覆盖（P1）**。测试 `tests/test_fact_log.py`（9 例，含 e23032 重放）。
- **影子接入 · `handler_message._shadow_commit_fact_log`** — 在权威 `save_state` 之后旁路写 fact + `project()`，把与线上 `state.json` 的 diff 追加到 `<session>/diagnostics/factlog_shadow.jsonl`；老 session 首遇时从上一轮 state 种子化一次（approach A 懒迁移）。全程 try/except 包住，**零行为变更**。
- **地基扩展（persona + 知情边界）· `fact_log` 实体层** — `Entity` 加稳定 `persona`（确立一次即锁定、叫法变了不丢 → 治"NPC 玩着变一个人"）+ `identity`；`Resolver` 消费 keeper 的 aliases 做归一；`commit_turn` 注册 actors + 锁 persona + 从 `knowledge_scope.npc_local` 派生 `knows` fact；`project()` 增出 `entity_persona` 与 `knowledge_boundary`（**白名单：实体不在其中 = 不知道任何隐藏事实**，治"知情边界退步"；证否约束故不靠检索）。测试增至 13 例。**归一边界**：只并助词变体 + keeper 已标的 aliases；keeper 没关联的同义碎片（面摊老板/面摊摊主/摊主）不自动并，留同义层/auditor。
- **可行性已验证** — e23032 40 轮重放：`onstage_match=true`，per-entity last_event 5 个不同值 vs 线上 1 个（P1 改善已体现在诊断里）。
- **归并增强 · commit `113ddbe`** — resolver 现还并 **前缀类别简称**（灰衣青年→灰衣青年修士）+ **晚到别名触发对已分裂实体的合并**（短工→桥上探头男人，消费 `scene_entities` 别名）；读时经 `canon_eid` 折叠、不改 append-only 日志。仍欠并防过并：同义词（灰衣/灰布衫）、双字名（张三/张三丰）不自动并。
- **步骤 2 第一刀（narrator 接管）· commit `8cd77ad`** — `narrator_input` 新增 **【人物档案·权威】块**（fact-log 投影：归并名+别称 + 锁定 persona + 知情边界白名单），插在旧【知情边界】/【人物注册表】前、声明冲突以它为准；`handler_message._load_factlog_view` 读上一轮日志注入 context。开关 `THREADLOOM_FACTLOG_NARRATOR`（默认开）+ try/except 回退。**首次行为变更**。`project()` 增 `entity_aliases`。b93051 验证：短工/桥上探头男人、灰衣青年/灰衣青年修士 各归并一行。全量 548 passed。
- 探针 `scripts/factlog_probe.py`（真实数据快速验证，可独立重跑）。
- **canonical 升级到专名 · commit `6ca80b5`** — 实体获得专名样别名（沈昭）时，canonical 从初始描述（灰衣青年修士）单向升级到专名；`_looks_like_proper_name` 保守判定（长度 2-4 + 无类别后缀 + 无服务角色词 + 无描述字），短工/摊主/灰衣青年修士 不升。b93051 验证：沈昭升为主名。
- **persona 固化（自动提炼）· commit `6ca80b5`、修复 `84c9ba5`** — consolidation turn 对"有戏份(present≥3)但无 persona"的 NPC 各跑**一次** LLM（`persona_distiller.distill_persona`，role=state_keeper_candidate）提炼**稳定性格**并锁定；只写"是个怎样的人"、**排除对主角的态度/关系**（那是动态的、不写死）。`FactLog.entity_observations / personaless_active` 供料，`handler_message._consolidate_factlog_personas` 挂 consolidation、guarded、flag-gated。修复 `84c9ba5`：keeper 档模型常把回答包成 JSON 或回显 prompt，`_clean_persona_text` 剥 JSON + 校验拒绝回显/残留/过长，避免坏 persona 锁死污染权威块。
- **narrator 模型适配** — 见 `prompts/runtime-rules*.md`、`doc/OPERATIONS.md`：grok 用去 jailbreak、鼓励铺陈、反套路的 `runtime-rules-grok.md`（`context_builder` 按 narrator 模型名切换）；默认与 grok 规则都加了**反脑补**条款（不许把未出现的既定事实写成定论，环境铺陈豁免），与 output 端 grounding guard 双道。
- **P2 关系事件线（roadmap）· commit `91f59c8` / `b959714`** — `relation` fact（关系 label 变才追加、带 evidence + span + 去箭头）；`project()` 投影 `entity_relationship`（当前=最新、**动态不锁**）+ `entity_relationship_history`（带 turn/why 的关系线）；权威块展示"对主角=<关系>（依据）"。b93051 验证：沈昭 戒备→初步信任→初识→相知。

**下一步 / 双轨写回进度**（详见 `doc/WORKPLAN-FACTLOG-DUAL-TRACK.md`）：

- ✅ **步骤 2 名单写回路径**（默认关）：`THREADLOOM_FACTLOG_WRITE_IMPORTANT=1` 时，`save_state` 前 `commit_turn` + `merge_projected_important_npcs` 成为 `important_npcs` 唯一权威写入，跳过 tracker/continuity；schema 合并（投影管 last_event/成员，prev 保留 locked/aliases 等）。regenerate/delete 接 `truncate_after`。  
- ✅ **投影名单治理**：ephemeral 路人过滤 + **inactive ≥20 淡出**（persona 锁定例外）；实体/facts 不删。  
- ✅ 真实 session 基线（e23032/b93051/c88796 等）：P1 clobber 与名单膨胀改善明显；欠并（掌柜/周掌柜）、策略差仍在 → **未默认开**。  
- 待做：手测（**新档或 session 副本即可**，不绑某条旧剧情）→ 默认开 → `WRITE_ONSTAGE` → 删旧 reconciliation；脆点仍在——归并依赖 keeper 别名、重建受 regenerate 改写影响。观察/开关见 `doc/OPERATIONS.md`。
