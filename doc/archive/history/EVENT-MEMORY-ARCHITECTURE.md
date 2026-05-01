# Event Memory Architecture

这份说明专门澄清当前系统里两类“记忆整理层”的职责：

1. 细粒度事件索引层：`event_summaries`
2. 状态整理层：按配置周期运行的 `state_keeper` consolidation

它们都在描述“发生了什么”，但时间尺度、用途和服务对象不同。

## 一、当前结论

当前 narrator **不直接读取** `event_summaries` 文件。

当前 narrator 主链主要吃的是：

- `runtime-rules.md`
- 当前 active preset
- `character-data.json`
- slim 玩家档案
- `canon`
- 当前硬锚点（time / location / main_event / onstage / relevant）
- 最近 12 轮
- selector 命中的候选知识块（如 lorebook / NPC candidates / npc profiles）
- actor registry、active 物件、`knowledge_records` 等连续性层

其中：

- narrator 现在不直接读取 `memory/event_summaries.json`
- narrator 也不直接读取 `summary.md` 作为主真相源

也就是说，当前 narrator 主要吃的是：

- 近程上下文（最近 12 轮）
- 当前 state
- selector 注入的补充块

## 二、细粒度事件索引层：event_summaries

### 文件

- `memory/event_summaries.json`

### 当前用途

- 每隔若干轮（当前是前两轮保留 + 后续每 3 轮一次）生成一条短事件摘要
- 记录为 session-local 事件索引层
- 当前主要用于：
  - 后续 selector 接入的准备
  - 调试/trace 观察

### 当前字段

- `event_id`
- `turn_id`
- `summary`
- `actors`
- `objects`
- `clues`
- `scene_shift`
- `provider`

### 当前边界

- 它不直接改 narrator prompt
- 它不直接写最终 state
- 它更像“近程事件索引”

## 三、状态整理层：keeper consolidation

### 触发

- 首轮 / bootstrap：完整 `state_keeper`
- 高频 skeleton：完整回复后产出最小骨架
- 完整 fill keeper：按 consolidation 配置周期运行，当前默认偏增量 patch

### 当前用途

- 对整个 state 做系统性收束
- 处理：
  - `main_event`
  - `immediate_risks`
  - `carryover_clues`
  - `tracked_objects`
  - `possession_state`
  - `object_visibility`
  - `knowledge_scope`
  - `graveyard_objects`
- 并在 merge 后影响：
  - `main_event`
  - `onstage_npcs`
  - `relevant_npcs`
  - `important_npcs`
  - `active_threads`

### 当前边界

- 这是 keeper 的长期 state 整理层
- skeleton 层维护当前骨架，fill 层维护增量信号、物件和本轮知情 delta
- `knowledge_scope` 不长期累积；长期知识由 `knowledge_records` 保存
- active object 不直接删除，消耗/摧毁/遗失/归档会进入 `graveyard_objects`
- 它不是“短事件索引”

## 四、为什么它们不能互相替代

### event_summaries 不能替代 keeper consolidation

因为它只记录：

- 某几轮里最关键的局势变化
- 更适合检索与回流

它不负责：

- 全局 state 收束
- 关系统一
- 物件与 knowledge_scope 的系统整理
- 物件生命周期、holder 合法性和长期 knowledge_records 去重

### keeper consolidation 不能替代 event_summaries

因为它职责不同：

- 默认每 2 轮运行一次，仍不是每轮事件索引
- 不是索引层
- 不适合回答“最近哪一轮开始发生这件事”

## 五、当前推荐关系

```text
细粒度 event_summaries -> 服务 selector / 近程事件检索
keeper consolidation -> 服务 keeper / state 稳定
```

它们：

- 不该完全混成一个东西
- 也不该被误解成完全独立、互不相关
- 更合理的理解是：它们都属于 keeper memory 体系，但时间尺度不同

## 六、当前系统真实状态

截至当前版本：

- `event_summaries` 已经落地并会写入 session-local 文件
- selector 已开始把 `event_summaries` 作为第一层命中索引
- 只有命中旧事件时，selector 才会进一步允许长程 `summary` 注入 narrator
- narrator 仍然不直接读取 `event_summaries` 文件本身，而是只在 selector 决定后吃到更长的 `summary_text`

所以如果你现在问：

> narrator 吃不吃 event？

答案是：

**当前不吃。**

当前 narrator 主要吃的是：

- 最近 12 轮
- 当前 state
- selector 的候选知识注入块

而不是 `event_summaries` 本身。

## 七、后续方向

如果后面继续演进，最合理的下一步是：

- 让 selector 先命中 `event_summaries`
- 命中后再决定是否把更详细的旧事件上下文补给 narrator

也就是说：

- 先让 `event_summaries` 服务 selector
- narrator 只在 selector 命中旧事件且判断需要时，才间接吃到更长的 `summary_text`

## 八、Keeper 每轮保存地图

当前 `POST /api/message` 的保存入口集中在 `backend/handler_message.py`，底层文件路径由 `backend/runtime_store.py::session_paths()` 定义。

### 每轮一定或通常写入

- `memory/history.jsonl`
  - 正常完整回合追加 2 条：`user` 输入和 `assistant` 回复。
  - partial 回复也会追加，但 assistant item 会带 `completion_status`。
  - 这是 transcript 主记录，允许一轮两条，不属于重复写入。

- `memory/state.json`
  - 保存当前 keeper state，是覆盖写，不是追加写。
  - 一轮内可能出现多次 `save_state()`：例如 fragment fallback、`update_state()` 后、thread/important NPC 合并后。
  - 这些是阶段性覆盖，最终以最后一次写入为准；风险不是“重复记录”，而是前后阶段字段互相覆盖。

- `meta.json`
  - 更新 `last_turn_id`。
  - 如果请求带 `client_turn_id`，会缓存完整 response 到 `processed_client_turn_ids`。
  - 重复 `client_turn_id` 会直接返回缓存 response，不再追加 history/state/event/trace，是当前主要幂等闸门。

- `turn-trace/<turn_id>.json`
  - 每轮保存一份 trace，包含 context 摘要、narrator、skeleton keeper、state keeper、post state 等调试信息。
  - 同一 `turn_id` 的 trace 是覆盖写；正常不产生多份重复 trace。

### 按条件写入

- `memory/event_summaries.json`
  - 由 `append_event_summary()` 追加事件索引项。
  - 当前触发频率是前两轮保留，之后每 3 轮一次。
  - 文件内保留最近 80 条；它是中程事件索引，不是完整 state，也不直接作为 narrator 主输入。

- `memory/summary.md`
  - 每个完整 runtime 回合会调用 `update_summary()` 覆盖生成阶段摘要。
  - 当前主要作为长程压缩/调试产物；只有 selector 判断需要时才间接回流 narrator。

- `memory/keeper_record_archive.json`
  - 由 `keeper_archive` 从 history 的 user/assistant 对构建中程 archive。
  - `retrieve_keeper_records()` 在 archive 缺失、损坏或落后时刷新；刷新默认使用 `skip_bootstrap=True, use_llm=False`，避免读取链触发额外 LLM/bootstrap 写入。
  - archive 窗口会排除最近 overlap pairs，避免把近程窗口和中程 archive 重叠注入。
  - refresh / upsert 前会删除 `end_pair_index > current_pair_count` 的未来 records，避免 undo / regenerate 后旧分支污染召回。

- `persona/*`
  - `update_persona()` 会按候选连续性信息更新 session-local persona 文件。
  - 这是人物连续性层，不是 keeper 主 state 的替代源。

### 分支差异

- opening menu / opening guard
  - 只写 history、meta、trace；不跑完整 keeper。

- opening choice
  - 会跑 `state_fragment -> skeleton keeper -> fill keeper -> thread/important_npc` 写回链。
  - 该分支可能先保存 opening state，再保存 keeper 合并后的最终 state。

- runtime complete
  - 跑 narrator、完整回复后跑 skeleton keeper、按首轮/bootstrapped/2 轮 consolidation 规则跑完整 state keeper 或 fragment baseline。
  - 完整回合追加 history，再合并 arbiter/thread/important NPC，最后覆盖 `state.json` 并更新 event summary / summary / persona / meta / trace。

- runtime partial
  - 只追加 partial history，更新 meta 和 trace。
  - 不继续写 keeper state，避免不完整 narrator 回复污染事实层。

### 重复与污染风险结论

- 未发现 `client_turn_id` 重复请求会重复追加 history 或 event summary；重复请求命中 `meta.processed_client_turn_ids` 后直接返回缓存 response。
- `state.json` 的多次保存是同轮覆盖型写入，不会制造重复记录，但要关注后写阶段是否用旧字段覆盖新 keeper 结果。
- `event_summaries.json` 是追加型文件，目前按 turn 频率追加；如果未来引入重试/再生成，需要以 `turn_id` 做去重保护。
- `keeper_record_archive.json` 是派生缓存；刷新会先 prune 未来 records，再按窗口补齐，不应反向写 state/history。
- 当前主要污染链风险来自结构化抽取质量：噪声 object label、畸形 NPC 名称或片段化 main_event 进入 `state.json` 后，会被 selector/narrator 作为上下文继续消费。

### Keeper 实体与物件合并规则

当前 `state.json` 中的 `scene_entities` 与 `tracked_objects` 不再按每轮抽取结果全量替换，而是走稳定实体优先的增量合并：

- 已存在的 NPC 优先保留 `entity_id`、更具体的 `primary_label`、已确认 `role_label` 与已有细节字段。
- 后续抽取如果只给出更泛称呼，例如从 `来福客栈老板` 退化成 `客栈老板`，不会覆盖旧主称呼。
- 后续抽取如果确认是新人物，例如 `九芝堂老板` 而不是 `来福客栈老板`，才新增一个新的 `scene_entities[]` 项。
- 已存在的关键物件优先保留 `object_id`、更具体的 `label` 与非泛化 `kind`。
- 后续抽取如果把 `来福客栈账册` 退化成 `账册`，不会覆盖旧标签。
- 噪声物件标签，例如动作残片或 `的包` 这类局部短语，会在标准化时过滤。
- `tracked_objects` 只保留 active 物件；`lifecycle_status=consumed/destroyed/lost/archived` 的物件会退出 active 层并写入 `graveyard_objects`。
- keeper object patch 只表达本轮明确变化，不应把 baseline 全量对象重新写回 payload。

### NPC 与物件双向绑定

当前物件归属以 `possession_state` 为事实来源，标准化层会自动把它回写成 NPC 与物件的双向绑定：

- `possession_state[].holder` 会按 `scene_entities[].primary_label / aliases` 对齐到稳定主名。
- 新 holder 必须能在当前人物、scene entities、actor registry 或 protagonist aliases 中找到；凭空 holder 不覆盖旧合法归属。
- `tracked_objects[]` 会派生：
  - `owner`
  - `owner_type`
  - `bound_entity_id`
  - `bound_entity_label`
  - `possession_status`
- `scene_entities[]` 会派生 `owned_objects[]`，记录该 NPC 当前绑定的关键物件摘要。
- keeper fill prompt 只需要输出增量物件变化和 `possession_state`，不需要为了绑定而重写整个人物表。
