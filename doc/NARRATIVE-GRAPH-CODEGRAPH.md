# CodeGraph 与 Threadloom 叙事记忆相关性分析

**日期**：2026-05-24  
**外部参考库**：[`colbymchenry/codegraph`](https://github.com/colbymchenry/codegraph)  
**考察提交**：`f366222dbd6b7e43047072a9417289b1b02ae457`

## 结论

`codegraph` 不适合直接作为 Threadloom 的叙事记忆引擎，但它的架构思想高度相关：

- 本地预索引知识图；
- typed nodes / typed edges；
- SQLite + FTS5 的本地检索层；
- source span / provenance；
- 面向任务的 context builder；
- 增量同步与派生缓存失效；
- impact analysis 风格的关系扩展查询。

Threadloom 应借鉴的是“**本地 typed graph index + source evidence + budgeted context builder**”，而不是借用代码 AST / call graph 的具体语义。

推荐定位：未来的 `narrative_graph` 应先作为 **只读派生索引**，覆盖现有 `state / actor registry / objects / knowledge_records / event_summaries / summary_chunks / keeper archive / history shards`，服务 selector、审计和证据回源；不应直接替代 `canon/state/keeper archive/actor registry`，也不应直接写回叙事真相。

## codegraph 的核心设计

`codegraph` 是面向 AI coding agent 的本地代码知识图。它先把代码库解析成 symbol graph，再让 agent 通过 MCP 工具查询结构化上下文，而不是每次重复 grep / read。

核心流程：

1. 使用 tree-sitter 解析源代码 AST。
2. language extractor 产出 symbol node 与 relationship edge。
3. 写入本地 SQLite 数据库。
4. 使用 FTS5 支持全文搜索。
5. resolver 连接 calls / imports / inheritance / framework route 等关系。
6. context builder 根据任务查询 entry points，再做图扩展与代码片段提取。
7. watcher / sync 用内容 hash 与 git status 做增量更新。

主要结构：

- `nodes`：函数、类、接口、变量、文件、route 等 symbol。
- `edges`：`contains / calls / imports / exports / extends / implements / references / type_of / returns / instantiates / overrides / decorates` 等关系。
- `files`：文件路径、内容 hash、语言、大小、mtime、索引时间、节点数、错误信息。
- `unresolved_refs`：暂未解析的引用。
- FTS5：索引 `id / name / qualified_name / docstring / signature`。

这些设计里，最值得 Threadloom 借鉴的是：**本地索引不是权威事实本身，而是为检索、解释和上下文构建服务的结构化加速层**。

## 与 Threadloom 当前架构的对应关系

Threadloom 已经不是 transcript-only 系统。当前事实面包括：

- `runtime-rules`：长期世界运行规则与控制权边界；
- `character core / lorebook`：角色卡世界设定与候选知识；
- `state`：当前场景结构化状态；
- `actor registry`：长期人物基础设定、alias、关系与 actor-id 绑定；
- `tracked_objects / possession_state / object_visibility / graveyard_objects`：物件状态与生命周期；
- `knowledge_scope`：本轮新增知情 delta；
- `knowledge_records`：actor-id keyed 长期知情记录；
- `event_summaries`：中程事件索引；
- `summary_chunks`：固定 12 轮长程摘要 chunk；
- `keeper_record_archive`：中段结构化归档；
- `history.jsonl / history_shards`：历史正文与证据回源；
- `turn trace`：regenerate / delete 的安全回滚证据。

这与 `codegraph` 的相似点在于：两者都需要把大量原始文本/文件转成可查询结构，再按任务构建有限上下文。

关键差异在于：

- 代码图的节点来自确定性 AST；叙事图的节点来自 prose、LLM keeper、deterministic normalization 与用户输入。
- 代码图的关系多是静态结构；叙事图的关系有时间范围、视角、知情者、证据来源、当前有效性与分支回滚问题。
- 代码图可以较强信任 parser；叙事图必须始终回源到 recent window、history evidence、state 或角色卡设定。
- 代码图的 call graph 不等于叙事因果链；Threadloom 需要 `SUPPORTED_BY / SUPERSEDES / CONTRADICTS / OBSERVED_BY / KNOWN_BY` 等证据边界。

## 可借鉴点

### 1. 本地优先索引

Threadloom 当前不宜在 v1.x 主链强依赖外部 memory server、向量库或额外每轮 LLM 抽取。`codegraph` 的 SQLite 本地索引方向更贴合当前部署口径。

建议：在 session 目录下建立派生索引，例如：

```text
memory/narrative_graph.sqlite
```

它应当像 `summary_chunks`、`keeper_record_archive` 和 `history_shards` 一样是可重建派生缓存，而不是唯一真相源。

### 2. typed nodes / typed edges

`codegraph` 的价值来自明确 node / edge 类型。Threadloom 可以建立叙事版类型系统。

候选节点：

- `Actor`
- `Protagonist`
- `Object`
- `Location`
- `Event`
- `SceneObjective`
- `Signal`
- `Claim`
- `KnowledgeRecord`
- `Relationship`
- `SourceSpan`
- `LorebookEntry`
- `SummaryChunk`
- `KeeperRecord`

候选边：

- `APPEARED_IN`
- `MENTIONED_IN`
- `SUPPORTED_BY`
- `SUMMARIZED_BY`
- `SUPERSEDES`
- `CONTRADICTS`
- `LOCATED_AT`
- `HOLDS`
- `VISIBLE_TO`
- `KNOWN_BY`
- `BELIEVED_BY`
- `OBSERVED_BY`
- `RELATIONSHIP_TO`
- `RESOLVED_BY`
- `CAUSED_OR_ENABLED_BY`

这些边不应被 narrator 直接当成“当前事实”。它们的作用是辅助 selector 找到证据、解释召回原因、控制 prompt 预算。

### 3. source span / provenance

Threadloom 近期加入的 history evidence pack 已经证明：长程历史不能只给摘要或事件索引，必须能回源原文。

叙事图中每个 `Claim / Event / Relationship / KnowledgeRecord / ObjectState` 都应该能追到至少一个 `SourceSpan`：

- source type：`history_turn / state / event_summary / summary_chunk / keeper_record / lorebook / player_profile / character_core`；
- source id：`turn_id / event_id / chunk_id / archive_record_id / lorebook_entry_id`；
- text range 或 excerpt；
- pair index / turn id；
- generated_from 或 derived_from；
- confidence / extraction method。

原则：**摘要负责召回，原文证据负责断言**。

### 4. budgeted context builder

`codegraph` 的 context builder 有 max nodes、max code blocks、depth、score 等预算。Threadloom selector 也需要同类预算：

- 最多注入多少事件；
- 最多回源多少历史正文；
- 是否需要 summary chunk；
- 是否需要 keeper archive；
- 是否需要 NPC profile；
- 是否只输出 index，不输出 prose；
- 是否因 mundane / low-pressure turn 降低召回。

未来可以让 `narrative_graph` 为 selector 提供 entry points 与扩展结果，但最终仍由 `context_builder.py` 决定 prompt block。

### 5. 增量同步与派生缓存失效

`codegraph` 用 file hash 与 git status 跳过未变化文件。Threadloom 可以借鉴为 artifact-level version：

- `history_manifest.json` 的 pair count / shard mtime / shard hash；
- `state.json` hash；
- `event_summaries.json` revision；
- `summary_chunks.json` revision；
- `keeper_record_archive.json` revision；
- `turn_trace` revision。

当 regenerate / delete / repair 改变历史或派生层时，graph index 应能按 revision 判断自己是否过期，并触发局部重建或整库重建。

### 6. impact analysis

`codegraph` 可查一个 symbol 影响哪些 callers / callees。Threadloom 可以做叙事版 impact analysis：

- 某个 actor 的 alias 被 canonicalize 后，哪些 event / summary / keeper record 需要迁移？
- 某个 object 被 consumed / destroyed 后，哪些旧 possession edge 需要 supersede？
- 某个 NPC 不知道主角私密身份时，哪些候选上下文不能让该 NPC 在对白中使用？
- 某条 old claim 与 recent window 冲突时，哪些 summary chunk / event hit 应降权或 quarantine？

这类分析更适合 debug / audit / repair，第一阶段不应直接自动改写事实层。

## 不应照搬的点

### 1. AST / symbol 语义

代码的 `function/class/import/call` 不对应叙事的 `actor/event/claim/knowledge`。Threadloom 需要的是叙事事实、证据、视角、时间范围和有效性。

### 2. call graph 因果

`calls` 表示程序结构调用，不代表故事因果。叙事里的“因为 / 导致 / 所以”必须有原文证据或 keeper 明确结构支持，不能靠摘要拼接。

### 3. 过度信任索引

代码图可较强信任 AST；叙事图不能较强信任 LLM 抽取结果。graph hit 只能表示“可能相关”，不能直接证明“已经发生 / 当前仍成立 / 某 NPC 已知情”。

### 4. watch 模型

Threadloom 的更新点不是任意文件变化，而是完整 turn transaction：user input → narrator → keeper → deterministic merge → save。比起 OS watch，更重要的是 transaction 后的精确 invalidation。

### 5. 额外每轮 LLM 抽取

当前统一记忆事务已经尽量避免多路 LLM 对同一轮剧情各自写回。`narrative_graph` 初期应从现有 committed artifacts 派生，避免新增每轮 graph extractor LLM。

## Threadloom 版 narrative graph 的目标边界

### 应做

- 作为 session-local derived cache；
- 从已提交 artifact 构建；
- 保留 source span 与 provenance；
- 改善 selector recall、debug explainability、audit；
- 支持 regenerate / delete 后重建；
- 保持角色卡无关，不写死剧情名词；
- 明确时间范围、知情者、可见性和 supersede 关系。

### 不应做

- 不替代 `state.json`；
- 不替代 `actor registry`；
- 不替代 `keeper archive`；
- 不直接覆盖 `knowledge_records`；
- 不把 summary 当作事实证据；
- 不让 graph edge 直接进入 narrator 当成无条件真相；
- 不强依赖外部服务；
- 不引入必须每轮额外调用的 LLM 抽取器。

# Narrative Graph 实施方案

## 总体路线

分三阶段实施：

1. **只读索引**：从现有 artifact 构建 `narrative_graph`，不接入 narrator prompt。
2. **selector 辅助**：让 selector 使用 graph 做候选召回，但 prompt 仍由现有 evidence pack / source hit 机制回源。
3. **审计与修复辅助**：用 graph 做冲突检测、stale edge 检测、knowledge boundary 检测，先只报告，后续再考虑 typed repair。

第一版目标不是“智能记忆引擎”，而是“**可重建、可解释、可回源的叙事索引**”。

## 阶段 0：设计与文档冻结

目标：明确边界，避免以后把 graph 当成第二套真相源。

工作项：

- 在架构文档中记录 `narrative_graph` 是派生缓存。
- 规定 graph 只读来源：`state / event_summaries / summary_chunks / keeper_archive / history_shards / lorebook / player_profile`。
- 规定 graph 输出只能进入 selector/debug/audit，不能直接覆盖 state。
- 规定任何旧历史因果断言必须回源 `SourceSpan`。

验收：

- 文档明确“graph hit != factual assertion”。
- 文档明确 regenerate/delete 必须使 graph 失效或重建。

## 阶段 1：最小只读 SQLite 索引

目标：建立 session-local graph cache，不改变现有运行结果。

建议文件：

```text
backend/narrative_graph.py
tests/test_narrative_graph.py
```

建议数据文件：

```text
memory/narrative_graph.sqlite
memory/narrative_graph_manifest.json
```

最小表：

```sql
nodes(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  stable_key TEXT,
  payload_json TEXT NOT NULL,
  created_from TEXT NOT NULL,
  first_turn_id INTEGER,
  last_turn_id INTEGER
)

edges(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  source_span_id TEXT,
  first_turn_id INTEGER,
  last_turn_id INTEGER,
  valid_from_turn INTEGER,
  valid_to_turn INTEGER
)

source_spans(
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  turn_id INTEGER,
  pair_index INTEGER,
  excerpt TEXT NOT NULL,
  payload_json TEXT NOT NULL
)

fts_entries(
  id TEXT PRIMARY KEY,
  node_id TEXT,
  source_span_id TEXT,
  text TEXT NOT NULL
)
```

第一版节点来源：

- `state.actors` → `Actor`；
- `state.tracked_objects` → `Object`；
- `state.knowledge_records` → `KnowledgeRecord`；
- `event_summaries` → `Event`；
- `summary_chunks` → `SummaryChunk`；
- `keeper_record_archive` → `KeeperRecord`；
- `history_shards` turn pair → `SourceSpan`。

第一版边：

- Actor `MENTIONED_IN` Event / SourceSpan；
- Object `MENTIONED_IN` Event / SourceSpan；
- KnowledgeRecord `SUPPORTED_BY` SourceSpan；
- Event `SUMMARIZED_BY` SummaryChunk；
- Object `HELD_BY` Actor；
- Object `VISIBLE_TO` Actor；
- Actor `KNOWS` KnowledgeRecord；
- Actor `RELATIONSHIP_TO` Protagonist；
- newer state edge `SUPERSEDES` older state edge when object holder/location/lifecycle changes。

Manifest：

```json
{
  "schema_version": 1,
  "session_id": "...",
  "history_pair_count": 0,
  "history_manifest_hash": "...",
  "state_hash": "...",
  "event_summaries_hash": "...",
  "summary_chunks_hash": "...",
  "keeper_archive_hash": "...",
  "built_at": "..."
}
```

验收：

- 构建 graph 不改变 narrator prompt。
- 删除 `narrative_graph.sqlite` 后可完整重建。
- manifest 过期时自动重建或 fallback 为不用 graph。
- 测试覆盖空 session、只有 state、只有 history shard、regenerate 后 pair count 变小等情况。

## 阶段 2：查询 API 与 debug 输出

目标：先让开发者看见 graph，不影响模型。

建议函数：

```python
build_narrative_graph(session_id: str) -> NarrativeGraphBuildResult
load_narrative_graph_status(session_id: str) -> NarrativeGraphStatus
query_narrative_graph(session_id: str, query: str, *, limit: int = 20) -> NarrativeGraphQueryResult
find_related_evidence(session_id: str, anchors: list[str], *, limit: int = 8) -> list[EvidenceHit]
```

debug 可返回：

- graph 是否存在；
- schema version；
- manifest 是否 stale；
- nodes / edges / source_spans 数量；
- query 命中 entry points；
- expansion edges；
- 最终 evidence hits；
- 每条 hit 的 source span。

验收：

- `/api/message` debug 中可选显示 graph status，但默认不增加 prompt。
- 查询结果每条都有 source span 或明确标记为 state-derived。
- 没有 source span 的结果不能作为旧历史证据输出。

## 阶段 3：selector 辅助召回

目标：让 graph 只帮助“找候选”，不直接替 narrator 断言。

接入点：

- `backend/selector.py`：把 current user text、recent scene、location、actors、objects 作为 anchors 查询 graph。
- `backend/context_builder.py`：对 graph hits 做 source hydration，复用 history evidence pack 原则。
- `backend/narrator_input.py`：不新增“图事实”大块；只在必要时把回源后的 `历史原文证据包` 或现有 block 扩充。

召回策略：

1. 从 current turn 抽 anchors：人物、地点、物件、事件短语、关系/来历/原因类意图。
2. graph 查 entry nodes。
3. 按边扩展一跳或两跳。
4. 过滤：
   - 不符合 current scene；
   - weak token only；
   - mundane object turn；
   - low-pressure turn 旧压力；
   - 与 recent window 冲突；
   - 只有 summary 没有 source span。
5. 对剩余结果回源原文。
6. 输出 evidence pack 或 event hit。

验收：

- graph 辅助关闭时，现有测试仍通过。
- graph 辅助开启时，prompt 中旧历史断言仍必须有原文 evidence。
- 普通吃饭/休息/移动 turn 不因 graph 召回大量旧事件。
- 背景追问/来历追问可比现有 event recall 更稳定找到较早 first-contact / origin 片段。

## 阶段 4：审计与冲突检测

目标：做只读诊断，不自动修真相。

候选审计：

- `Knowledge leak`：NPC 使用了不在其 `KNOWN_BY / VISIBLE_TO` 边里的私密信息。
- `Object resurrection`：graveyard object 后续又出现 active possession。
- `Stale location`：物件或 NPC 的 old location edge 与 recent window 冲突。
- `Alias split`：同一个 actor alias 在多个 actor 上冲突。
- `Summary unsupported claim`：summary chunk 中 claim 找不到 source span。
- `Event contradiction`：event summary 与 recent full prose 或 state edge 冲突。

验收：

- 审计报告只写 diagnostics，不进 narrator prompt。
- 每条问题给出 source spans 与建议修复方向。
- 自动修复必须另行设计 typed repair，不能把审计文本写回事实层。

## 阶段 5：可选 typed repair

目标：在足够测试后，把少数确定性修复接入 repair 工具，不进入在线主链。

可考虑：

- alias canonicalization 辅助；
- stale object edge 清理；
- orphan source span 清理；
- regenerate/delete 后 graph rebuild；
- summary chunk quarantine 建议。

不建议：

- 自动创造新 actor；
- 自动改 NPC 知情；
- 自动改关系；
- 自动改剧情因果；
- 自动把 graph inference 写入 `state.json`。

## 测试计划

最小测试：

- graph build from empty session；
- graph build from state actors / objects / knowledge_records；
- graph build from event summaries；
- graph build from summary chunks；
- source span hydration from history shards；
- stale manifest fallback；
- regenerate/delete pair count shrink；
- graph query returns provenance；
- selector graph assist does not inject unsupported summary-only fact；
- mundane turn guard；
- private knowledge guard；
- object lifecycle supersede guard。

回归命令建议：

```bash
python3 -m pytest tests/test_narrative_graph.py tests/test_context_builder.py tests/test_selector_recall.py tests/test_history_shards.py -q
```

若接入 selector，还应跑：

```bash
python3 -m pytest tests/test_state_fragment.py tests/test_memory_transaction_guards.py -q
```

## 风险

- 图索引变成第二套事实源，导致与 state/recent window 分叉。
- summary-only claim 被误当作历史证据。
- graph 扩展过宽，普通 turn 召回旧压力或旧事件。
- 知情边界只建全局事实，没有 actor-specific visibility。
- regenerate/delete 后 graph 未失效，旧分支继续污染 selector。
- 为了图抽取新增每轮 LLM 调用，破坏统一记忆事务的收口。

## 推荐第一步

如果要开始实施，第一步只做：

1. 新增 `backend/narrative_graph.py`；
2. 新增 `memory/narrative_graph_manifest.json` 与 `memory/narrative_graph.sqlite` 的派生缓存约定；
3. 从 `state.actors / tracked_objects / knowledge_records / event_summaries / history_shards` 建最小只读图；
4. 加测试证明可重建、可失效、可查询 source span；
5. 暂不接入 narrator prompt。

这样既能保存 `codegraph` 的核心启发，也不会让新系统过早影响叙事输出。
