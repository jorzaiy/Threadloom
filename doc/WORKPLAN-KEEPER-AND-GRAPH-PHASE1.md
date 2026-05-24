# 工作计划：Keeper field-level partial-accept + Narrative Graph Phase 1

**日期**：2026-05-24
**来源**：session 九幽大陆-20260520-e23032 turn-0141 narrator 重复拒收事件之后的优化讨论
**配套文档**：`doc/NARRATIVE-GRAPH-CODEGRAPH.md`（graph 完整路线图，本计划只覆盖 phase 1）

---

## 背景

本计划合并两条独立优化线：

- **A. Keeper 字段级 partial-accept**：解决 keeper 偶尔输出"部分字段崩坏 → 整张 state 塌方到 fragment-baseline → 后续轮次失去上下文"这一高频痛点。属于既有 5 层防御的精化，不是新机制。
- **B. Narrative Graph Phase 1**：按 `doc/NARRATIVE-GRAPH-CODEGRAPH.md` 实施阶段 0 + 阶段 1 + 阶段 2 的最小集——只读 SQLite 索引、manifest 失效检测、debug 查询 API；**不**接 selector、**不**改 narrator prompt、**不**新增每轮 LLM 调用。是中长期 selector 准确性 / 审计 / repair 三件事的共同基建。

两条工作流互相独立，建议串行不并行（A 先，B 后）。

---

## 工作流 A：Keeper 字段级 partial-accept

### 目标
让 keeper 的输出在"部分字段崩坏"时不再整张 state 塌方到 fragment-baseline；只把崩的格回退到 prev_state，好的格保留。同时把"为什么被拒"喂回模型做定向 retry，对齐 narrator 已有的 corrective retry 机制。

### 改动文件
- `backend/state_keeper.py`（主要）
- `tests/test_state_keeper_partial_accept.py`（新增）
- `doc/OPERATIONS.md` / `doc/BACKEND.md`（说明）

### 任务清单

**A1. 抽出 per-field validator 表**
把当前 `_has_low_signal()` / `_validate_against_prev_state()` 里的聚合判断拆成一张表：
```
{field_name: validator(keeper_value, prev_value, narrator_reply) -> 'accept' | f'reject:{reason}'}
```
- 核心字段（time / location / main_event / onstage_npcs / immediate_goal）逐条独立 validator
- 非核心字段（carryover_signals、knowledge_scope、tracked_objects 等）按类别批量

**A2. 改 acceptance 流程为 per-field merge**
`call_state_keeper()` 当前是"整张 keeper output → validate → 通过则用 → 不通过则 fallback"。改为：
1. 跑 per-field validator
2. 构造 `merged_state`：每格独立选 keeper-output 或 prev_state
3. merged_state 至少满足 useful signal ≥ 2 才返回，否则才真正走 fragment-baseline

**A3. trace diagnostics 扩字段**
`state_keeper_diagnostics` 加：
- `field_acceptance: {field_name: 'kept' | f'rejected:{reason}' | 'prev_retained' | 'no_change'}`
- `provider_used` 新增值 `llm-fill-partial`，区分整盘通过和部分接受

**A4. 定向 corrective retry prompt**
对齐 narrator 的做法：当 per-field 拒收发生且 attempt < max 时，给 keeper 一次重试机会，system prompt 追加：
```
【上一次回复字段问题】
- 被拒字段：time, npc_relationships
- time 退化为占位符
- npc_relationships 与 narrator 正文中的 NPC 集合不匹配
请重写本轮，针对被拒字段补具体锚点。
```
仅限"被拒字段 ≥ 2 且 attempt < max"时触发，避免拖长延迟。

**A5. 测试**（`tests/test_state_keeper_partial_accept.py`）
- 全字段好 → 行为不变（回归）
- 全字段坏 → fragment-baseline（回归）
- time 好、onstage_npcs 退化 → time 保留 keeper，onstage_npcs 沿用 prev
- 定向 retry prompt 必须命名被拒字段
- `trace.field_acceptance` 形状正确
- merged_state useful signal 不足 → 仍走 fragment-baseline

### 预计工期
2.5–3 个工作日。

### 风险
- **per-field validator 比聚合 validator 更容易"过宽"**——某个字段 validator 漏掉退化模式，那一格就被放进 merged state。**缓解**：先保守，验证不过的字段一律 `prev_retained`，宁可不更新也不接收疑似退化。
- **merged_state 可能出现内部不一致**（如 location 是新场景但 onstage_npcs 还是旧场景）。**缓解**：A1 表里加一组"跨字段一致性 validator"，location 变更时强制 onstage_npcs 也走 keeper（要么一起接受要么一起回退）。

---

## 工作流 B：Narrative Graph Phase 1（只读派生索引）

### 目标
对齐 `doc/NARRATIVE-GRAPH-CODEGRAPH.md` 阶段 0 + 阶段 1 + 阶段 2 的最小集。**不**改变线上行为，只产出 session-local SQLite 索引和 debug API。

### 改动文件
- `backend/narrative_graph.py`（新增，主体）
- `backend/narrative_graph_extractors.py`（新增，按 source artifact 拆 extractor）
- `runtime-data/.../sessions/<sid>/memory/narrative_graph.sqlite`（派生 cache，不进 git）
- `runtime-data/.../sessions/<sid>/memory/narrative_graph_manifest.json`
- `tests/test_narrative_graph.py`（新增）
- `doc/ARCHITECTURE.md`（加 1-2 段："narrative_graph 是派生 cache，不是真相源"）
- `doc/NARRATIVE-GRAPH-CODEGRAPH.md`（从未提交移到提交，更新"已实施 phase 1"）

### 任务清单

**B1. Schema 与 DB bootstrap**
按 `doc/NARRATIVE-GRAPH-CODEGRAPH.md` L274-315 建 4 张表：
- `nodes(id, kind, label, stable_key, payload_json, created_from, first_turn_id, last_turn_id)`
- `edges(id, source_id, target_id, kind, payload_json, source_span_id, first_turn_id, last_turn_id, valid_from_turn, valid_to_turn)`
- `source_spans(id, source_type, source_id, turn_id, pair_index, excerpt, payload_json)`
- `fts_entries(id, node_id, source_span_id, text)`

加 `schema_version` 表存版本号，未来 migrate 不破坏旧 sqlite。

**B2. Manifest 与失效检测**
按 doc L341-353：算 `history_manifest_hash / state_hash / event_summaries_hash / summary_chunks_hash / keeper_archive_hash`，存到 `narrative_graph_manifest.json`。
`load_narrative_graph_status()` 比对当前 artifact hash 与 manifest 是否一致；不一致 → 标 stale → 下次 build 整库重建（增量先不做，phase 1 简单优先）。

**B3. State 抽取器**（actors / tracked_objects / knowledge_records → Actor / Object / KnowledgeRecord 节点）
最简单的一步，因为 state 已经是结构化的，直接转 node。每个节点 `stable_key` 用 actor_id / object_id / record_id。

**B4. Event / SummaryChunk / KeeperRecord 抽取器**
从 `event_summaries.json` / `summary_chunks.json` / `keeper_record_archive.json` 转节点。`SourceSpan` 引用各自的 `event_id / chunk_id / record_id`。

**B5. History shards → SourceSpan**
从 `history_shards/*.json` 读 turn pair，每个 pair 一条 SourceSpan。`text` 字段存 excerpt（前 N 字符），完整原文不入库（节省空间，需要时按 turn_id 回 shard 读）。

**B6. 边构建**（按 doc L327-337）
- Actor `MENTIONED_IN` Event / SourceSpan
- Object `MENTIONED_IN` Event / SourceSpan
- KnowledgeRecord `SUPPORTED_BY` SourceSpan
- Event `SUMMARIZED_BY` SummaryChunk
- Object `HELD_BY` Actor（从 possession_state）
- Object `VISIBLE_TO` Actor（从 object_visibility）
- Actor `KNOWS` KnowledgeRecord（从 knowledge_records.knower_id）
- 旧 state edge `SUPERSEDES` 新 state edge：phase 1 先不做跨快照比较，留 phase 2

**B7. Query API + tagged-union 安全闸门**
```python
def query_narrative_graph(session_id, query, *, limit=20) -> NarrativeGraphQueryResult
def find_related_evidence(session_id, anchors, *, limit=8) -> list[EvidenceHit]
```
关键设计：`EvidenceHit` 是 dataclass，强制 `source_span_id: str` 非空，或 `state_derived: bool=True` 显式标记。**没 source span 的 hit 在函数边界处就被丢弃**，不允许进 selector / narrator prompt。这是 doc L222 那条硬约束的代码化。

**B8. Debug API 接入**
在 `/api/message` debug snapshot 里加可选字段 `narrative_graph_status`（默认关，需要 query string 开启），返回 nodes/edges/source_spans 数量、manifest 是否 stale、上次 build 时间。**不**接 selector，**不**进 narrator prompt。

**B9. 测试**（按 doc L466-478）
- 空 session build → 空表，manifest 写入
- 只有 state，无 history shards → 节点齐、source span 为空
- 完整 session build → 所有节点类型都出现，边数量符合预期
- regenerate-last 后 pair count 减少 → manifest stale → 重建后 SourceSpan 数量减少
- 删除 sqlite 后 build → 完整恢复
- query 返回的每个 EvidenceHit 必须有 source_span 或 state_derived 标记（边界测试）
- mundane / 空 anchor query → 返回空列表，不抛错

### 预计工期
9–10 个工作日。

### 风险
- **变成第二套真相源**：phase 1 query API 没人用还好，等 phase 3 一旦接 selector，没 source span 的 hit 偷偷进 prompt 是最大隐患。**缓解**：B7 的 tagged union + 类型强约束在 phase 1 就立下规矩；CI 加一个 lint 检查 `EvidenceHit` 构造点，禁止 `source_span_id=None and state_derived=False`。
- **manifest stale 检测漏掉某个 artifact 的更新**：例如忘记把 actor_registry 的 revision 算进 hash。**缓解**：第一版只覆盖 doc 里列的 6 个 artifact，新增 artifact 走显式列表（不动态扫目录），减少静默漏算。
- **history_shards 巨大时 build 慢**：长 session 一次性 build 可能要十几秒。**缓解**：phase 1 全量重建可以接受，标 stale → 下次首个请求异步触发，不阻塞当前 turn；前端 debug 显示 "graph rebuilding..."。

---

## 排序 & 里程碑

**A 先 B 后**。理由：

1. **A 是线上即时收益**——keeper partial-accept 落地当天就能减少"keeper 一格崩 → fallback 全空"的现象，session e23032 这类长 session 直接受益。
2. **B 是基础设施投资**——phase 1 不改 selector 行为，对用户透明，是为 phase 3 铺路。先做完 A 可以让团队"看到改进"的信心，再投入 B 的两周。
3. **A 的 trace diagnostic 模式（field_acceptance）会被 B 复用**——B8 的 debug snapshot 字段命名规范、B7 的 tagged union 思想，都可以从 A3 学到经验。
4. **互不阻塞**：A 完全不碰 graph 相关代码，A 的 PR 合并后 B 起步零冲突。

### 里程碑

| 节点 | 内容 | 交付 |
|---|---|---|
| **M1** (A 完成，~3d) | Keeper partial-accept 上线 | 1 个 commit，新增 1 个测试文件 ~10 用例，trace 增 field_acceptance 字段，doc 更新 |
| **M2** (B1–B5, ~5d) | Graph schema + extractor，无 query API | 1 个 commit（或拆 5 个），sqlite 能 build，manifest 写入，测试覆盖 build |
| **M3** (B6–B9, ~5d) | Query API + debug 接入 + tagged-union 闸门 + 文档冻结 | 第二组 commit，debug snapshot 能查 graph status，doc/ARCHITECTURE.md 加章节，doc/NARRATIVE-GRAPH-CODEGRAPH.md 标记 phase 1 已实施 |

---

## 这轮明确不做的事

- 不动 selector 排序逻辑（向量召回、roster 抖动抑制、负反馈回路全部延后）
- 不把 graph 接入 selector（那是 doc 的 phase 3）
- 不为 graph 加任何额外每轮 LLM 调用（doc L201、L499 的硬约束）
- 不做 graph 增量更新（manifest stale → 整库重建即可，phase 1 简单优先）
- 不做 SUPERSEDES 边（跨快照 diff 留 phase 2）
- 不做审计 / 冲突检测（doc 的 phase 4）
- keeper 这边不改 input、不改 schema、不动 skeleton sidecar 协议

---

## 后续规划（脱出本计划范围）

完成 M1+M2+M3 之后，依据当时 trace 数据再决定下一步。预期候选：

- **Selector phase 3 接入 graph**（doc L392-422）：把 graph evidence 接入 selector 决策，仍由 context_builder 做最终预算。
- **Keeper #2（skeleton vs fill 真正双轨校验）**：在 partial-accept 数据沉淀够之后，决定哪些字段需要 skeleton 仲裁。
- **Selector 向量召回（之前讨论的 #4）**：如果 graph 落地后仍有大量"同义换说法漏召"，再加轻量 embedding 作 anchor 抽取辅助（doc L155 那句"最终仍由 context_builder 决定"的契合点）。
- **Graph phase 2-4**：SUPERSEDES 边、audit / repair。
