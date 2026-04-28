# Keeper 写入质量修复目标与现状说明

## 当前实施状态

状态：已实施并通过 keeper 相关回归测试。

验证命令：

```bash
PYTHONPATH="/root/Threadloom:/root/Threadloom/backend" pytest tests/test_keeper_*.py tests/test_state_fragment.py
```

验证结果：`31 passed`。

补充验证：

```bash
PYTHONPATH="/root/Threadloom:/root/Threadloom/backend" pytest tests/test_model_client.py tests/test_keeper_*.py tests/test_state_fragment.py
```

验证结果：`33 passed`。

已落地内容：

- `knowledge_scope` 改为本轮 delta，不再继承上一轮 scope。
- `knowledge_scope` 增加 fail-safe coercion，局部格式错误不拖垮整包。
- `knowledge_records` 在同一 holder 下做轻量相似去重。
- object patch 不再因为 possession / visibility 更新而回填 baseline 全量对象。
- object 支持 `lifecycle_status: active | consumed | destroyed | lost | archived`。
- 非 active object 退出 `tracked_objects / possession_state / object_visibility`，进入 `graveyard_objects`。
- `possession_state / object_visibility` 允许合法新状态覆盖旧状态。
- 非法 holder 不覆盖旧合法 holder。
- keeper archive refresh 前会 prune rollback 后的未来 records。
- state keeper / state keeper candidate 默认请求 JSON object 响应格式，降低 HTTP 成功但正文不可解析的 fallback 概率。
- 模型返回 `message.content` 为空时，会继续尝试 `reasoning_content` 和 `choice.text`，避免把可用 JSON 丢弃。
- keeper 解析失败时保留真实 `usage`、`raw_reply_empty`、`raw_reply_excerpt`，fallback 诊断不再误导为“模型没有调用”。
- full keeper 失败后，若 fragment/skeleton fallback 已经给出可用核心骨架，不再把 `state_keeper_bootstrapped` 强制置回 `false`，避免每轮进入 bootstrap retry 并跳过 skeleton keeper。
- full keeper 的 JSON 整包解析失败时，会尝试从坏 JSON 中局部 salvage `tracked_objects / possession_state / object_visibility / knowledge_scope`，减少物件和知情 delta 因尾部截断或局部坏字段而整包丢失。
- full keeper consolidation 默认频率从每 3 轮改为每 2 轮，降低非合并轮发生物件/知识变化后漏写的窗口。

## 2026-04-27 object/knowledge salvage 与 consolidation 频率调整

### 问题

旧的 `_parse_fill_payload()` 在 JSON 整包解析失败时，只会尝试 salvage `carryover_signals / immediate_risks / carryover_clues`。如果模型正文里已经包含可用的 `tracked_objects / possession_state / object_visibility / knowledge_scope`，但尾部 JSON 截断或另一个字段坏掉，物件和知情 delta 仍会随整包失败一起丢失。

同时 full keeper 默认每 3 轮运行一次，非 consolidation 回合只依赖 skeleton + fragment。skeleton keeper 只维护 `time / location / main_event / onstage_npcs / immediate_goal` 五个骨架字段，不负责 object、signal、knowledge。因此物件转移或新增知情发生在非合并轮时，漏写窗口偏长。

### 修复

修改点：

- `backend/state_keeper.py`
- `config/runtime.json`
- `config/runtime.example.json`
- `tests/test_state_fragment.py`

修复内容：

- 新增局部 JSON 字段提取逻辑，用于从坏 JSON 中提取完整的数组/对象字段。
- `_parse_fill_payload()` 在整包解析失败后，除 signals 外继续 salvage：
- `tracked_objects`
- `possession_state`
- `object_visibility`
- `knowledge_scope`
- consolidation 默认频率从 `3` 改为 `2`。
- 补充测试覆盖坏 JSON 中 object 与 knowledge 可被 salvage。

### 边界

salvage 只处理字段自身是完整 JSON 数组或对象的情况。如果该字段内部本身也被截断或格式损坏，仍会被丢弃，避免把半截坏结构写入 state。

## 2026-04-27 bootstrap fallback 循环修复

### 问题

排查 `碎影江湖-20260426-942316` 时发现，历史漏写的核心形态是 full `state_keeper` 多轮返回不可解析 JSON，handler 进入 `fragment-baseline` fallback。旧逻辑会在 fallback 后把 `state_keeper_bootstrapped` 置为 `false`。

这会产生放大效应：

- 下一轮被判定为 `needs_keeper_bootstrap`。
- bootstrap turn 会跳过 skeleton keeper。
- 系统再次直接调用 full keeper。
- full keeper 如果继续 JSON 解析失败，又回到 `fragment-baseline`，并继续保持未 bootstrap。

结果是：本应每轮更新核心骨架的 skeleton keeper 长期不运行，`time / location / main_event / onstage_npcs / immediate_goal` 更容易滞后，object、signal、knowledge 等 full keeper 字段也因解析失败持续漏写。

### 修复

修改点：

- `backend/handler_message.py`
- `tests/test_state_fragment.py`

修复内容：

- 新增 `_keeper_fallback_bootstrapped()`。
- full keeper 失败时，如果 fallback fragment/skeleton 已经提供可用核心骨架，则允许 `state_keeper_bootstrapped = true`。
- 只有 fragment 仍然明显不可用（例如核心字段仍是 `待确认` 或空）时，才继续保持未 bootstrap。
- 补充回归测试覆盖可用 fragment 退出 bootstrap 和不可用 fragment 保持未 bootstrap。

验证命令：

```bash
PYTHONPATH="/root/Threadloom:/root/Threadloom/backend" pytest tests/test_state_fragment.py
PYTHONPATH="/root/Threadloom:/root/Threadloom/backend" pytest tests/test_keeper_*.py tests/test_state_fragment.py
```

验证结果：`41 passed`。

### 边界

这次修复不等于 full keeper JSON 成功率已经完全稳定。它解决的是 fallback 后的 bootstrap 循环放大问题：即使 full keeper 暂时失败，后续回合也应恢复 skeleton keeper 的每轮核心骨架更新，减少“连续漏写”。

## 2026-04-27 额外修复与 session 记忆整理记录

本节用于区分两类结果：代码层 keeper 修复，以及 `碎影江湖-20260426-942316` 的人工记忆清理。后者不能作为“keeper 一开始自动写入质量已经很好”的证据。

### Keeper JSON 与诊断修复

在 `碎影江湖-20260426-942316` 的排查中，发现历史 fallback 的关键原因不是 HTTP 调用完全失败，而是模型返回内容无法被 `parse_json_response()` 解析，错误形态为：

```text
state_keeper_failed: Failed to parse JSON from model output:
```

旧诊断会在 fallback 后丢失真实 `usage` / raw reply 信息，导致 trace 中容易呈现为 `model_usage: null`，从而误判成 keeper 没有实际调用模型。

已修复内容：

- `backend/model_client.py`：支持透传 OpenAI-compatible `response_format: {"type": "json_object"}`。
- `backend/model_client.py`：当 `message.content` 为空时，继续尝试 `message.reasoning_content` 和 `choice.text`。
- `backend/model_config.py`：`state_keeper` 与 `state_keeper_candidate` 默认启用 JSON object 响应模式。
- `backend/model_config.py`：`resolve_provider_model()` 透传 `response_format`。
- `backend/state_keeper.py`：新增 `StateKeeperCallError`，解析失败时保留真实 `usage` 和 raw reply 摘要。
- `backend/handler_message.py`：keeper fallback 诊断保留 `model_usage`，并新增 `raw_reply_empty`、`raw_reply_excerpt`。
- `tests/test_model_client.py`：新增 `response_format` 透传与 `reasoning_content` 提取测试。

这组修复的目标是提高 keeper JSON 写入成功率，并让后续 trace 能区分：HTTP 调用成功、模型返回为空、模型返回非 JSON、JSON schema 不合格、fallback baseline 写入。

### `碎影江湖-20260426-942316` 人工记忆整理

为便于继续游玩该 session，已人工整理以下派生记忆文件：

- `runtime-data/default-user/characters/碎影江湖/sessions/碎影江湖-20260426-942316/memory/state.json`
- `runtime-data/default-user/characters/碎影江湖/sessions/碎影江湖-20260426-942316/memory/summary.md`
- `runtime-data/default-user/characters/碎影江湖/sessions/碎影江湖-20260426-942316/memory/keeper_record_archive.json`
- `runtime-data/default-user/characters/碎影江湖/sessions/碎影江湖-20260426-942316/memory/summary_chunks.json`

整理前的主要污染包括：地点滞后在 `神都东坊外巷口檐下`，旧潜行/暴露风险残留，`event-stealth-001` 残留，以及 keeper archive 中弱摘要继续描述巷口局势。整理后的当前锚点为：

- 当前地点：`神都坊署偏厅`
- 当前事件：陆小环在偏厅向文吏录口供
- 当前在场：`文吏`、`小差役`
- 关键相关人物：`年轻男子`、`巡捕`、`提灯首领`、`受伤皂衣人`
- 关键物证：`纸封`
- 关键线索：纸封由巡捕从医馆外役车上找到并带回坊署，内容未公开；年轻男子不是逃犯；受伤皂衣人称拿钱办事但不供雇主；提灯首领不开口

同时清理了 `潜行`、`event-stealth`、`被惊动压`、`待确认 黄昏` 等与当前阶段冲突或污染的记忆内容。

已创建整理前备份：

- `memory/state.json.pre-play-cleanup-20260427`
- `memory/summary.md.pre-play-cleanup-20260427`
- `memory/keeper_record_archive.json.pre-play-cleanup-20260427`

重要边界：上述 `942316` 当前高质量记忆是人工清理后的结果，不代表 keeper 在修复前或一开始就能自动生成同等质量。后续评估 keeper 自动能力时，应以清理后的新增回合 trace、`state_keeper_diagnostics`、`state.json` 增量变化和 selector 命中质量为准。

## 背景

Threadloom 的 keeper 线负责把 narrator 生成的叙事正文、玩家输入、当前结构化场景锚点转换为可持久化的运行时状态。

当前 keeper 已经形成多层结构：

- skeleton keeper：提取最小核心骨架。
- state keeper fill：基于模型补充本轮增量状态。
- state fragment：从 runtime context、arbiter、scene facts 构建基础锚点。
- state bridge normalize：统一清洗、去重、合并、绑定对象和人物。
- actor registry：维护长期人物注册表，并把物件、知识绑定到 actor id。
- keeper archive / retriever：把较早历史窗口压缩为可召回 records。

本次修复目标不是重写 keeper，而是稳定它的写入质量，确保 keeper 输出按“增量写入、稳定合并、长期记录分层保存”执行。

## Keeper 当前承担的任务

### 1. 场景核心状态维护

相关字段：

- `time`
- `location`
- `main_event`
- `immediate_goal`

职责：

- 记录当前场景的时间、地点、主事件和下一拍目标。
- 不应在没有明确证据时把稳定字段改回 `待确认`。
- skeleton keeper 主要负责这部分最小骨架。

### 2. 当前人物状态维护

相关字段：

- `onstage_npcs`
- `relevant_npcs`
- `scene_entities`

职责：

- 记录当前在场人物和短期相关人物。
- 保持 entity id 和人物称呼稳定。
- 不把环境、物件、动作片段误识别成人物。
- 不维护 NPC 长期基础设定；长期设定由 actor registry 负责。

### 3. 延续信号维护

相关字段：

- `carryover_signals`
- `immediate_risks`
- `carryover_clues`

职责：

- 记录后续仍会影响局势推进的风险、线索或混合信号。
- `carryover_signals` 是主结构，`immediate_risks` / `carryover_clues` 可由其派生。
- 不应把普通 prose、动作碎片、临时氛围写成长期信号。

### 4. 物件状态维护

相关字段：

- `tracked_objects`
- `possession_state`
- `object_visibility`

职责：

- 记录后续需要追踪的关键物件。
- 记录物件持有者、持有状态、位置和可见性。
- 只在正文出现明确持有、展示、转移、收起、放下、遗失、证物化等持续物理状态时写入。
- 不把一次性货币、临时消耗品、动作词、复合短语碎片误写为物件。

### 5. 知情边界维护

相关字段：

- `knowledge_scope`
- `knowledge_records`

职责：

- `knowledge_scope` 应表示本轮新增知情 delta。
- `knowledge_records` 是长期知识账本。
- 主角知道的信息、NPC 知道的信息必须分开。
- 主角看到不等于 NPC 也知道。

### 6. 长期归档与召回

相关模块：

- `keeper_archive.py`
- `keeper_record_retriever.py`

职责：

- 把最近窗口之外的历史压缩为 keeper records。
- retrieval 根据当前地点、人物、物件、主题召回相关旧窗口。
- archive 应保持历史摘要稳定，避免重复生成同一历史窗口导致漂移。

## 当前已具备的保护

### 1. 空列表不会清空旧数据

`_merge_keeper_fill()` 当前只在列表非空时覆盖：

- `immediate_risks`
- `carryover_clues`
- `tracked_objects`
- `possession_state`
- `object_visibility`

已有测试覆盖：

- `tests/test_state_fragment.py::test_keeper_fill_empty_lists_do_not_clear_existing_records`

### 2. actor registry 基础字段相对稳定

已有逻辑防止 keeper 或 scene entities 覆盖长期人物基础设定：

- `aliases`
- `personality`
- `appearance`
- `identity`

已有测试覆盖：

- `test_actor_registry_keeps_base_fields_immutable`
- `test_normalize_state_preserves_actor_registry_from_previous_state`

### 3. tracked object 有基础过滤

`state_bridge.py` 中已有坏物件标签过滤：

- 过长文本
- prose 标点
- 动作片段
- `的包`、`的手` 等残缺标签

已有测试覆盖：

- `test_normalize_state_keeps_stable_entities_and_objects_when_candidate_is_weaker`

### 4. object 与 actor 有双向绑定

`normalize_state_dict()` 和 `update_actor_registry()` 会把物件持有状态绑定到 actor id。

已有测试覆盖：

- `test_normalize_state_binds_owned_objects_to_npc_both_ways`
- `test_actor_registry_binds_items_and_knowledge_to_actor_ids`

## 当前主要风险

### 1. `knowledge_scope` 长期累积，违背本轮 delta 语义

位置：

- `backend/state_bridge.py`
- `normalize_state_dict()` 中的 `knowledge_scope` 合并逻辑

现状：

- state keeper prompt 要求 `knowledge_scope` 只记录本轮新增信息。
- 但 normalize 阶段会把 `prev.knowledge_scope` 与当前 `knowledge_scope` 合并。
- 后续 actor registry 每轮都会从整个 `knowledge_scope` 派生 `knowledge_records`。

风险：

- 旧知识被反复当作本轮新增处理。
- 误提取的知识一旦进入 `knowledge_scope`，容易长期滞留。
- `knowledge_scope` 与 `knowledge_records` 职责边界不清。

目标：

- `knowledge_scope` 保持本轮 delta。
- 长期知识只进入 `knowledge_records`。
- 本轮没有新知识时，不继承旧 `knowledge_scope`。

### 2. object patch 会携带 baseline 全量对象，扩大污染面

位置：

- `backend/state_keeper.py`
- `_coerce_object_layers()`
- `_merge_keeper_fill()`

现状：

- `_coerce_object_layers()` 会从 baseline 建 object index。
- 只要 payload 使用任一 object 字段，就可能把 baseline 全量 `tracked_objects` 写回 payload。
- 后续 `_merge_keeper_fill()` 会把这些字段视作 keeper 本轮输出。

风险：

- 本轮只想更新一个 possession，却变成全量 object candidate。
- 旧脏对象可能被重新强化。
- 无关旧对象可能参与本轮覆盖、去重和衰减判断。

目标：

- object fill 只写本轮明确变化。
- baseline 只能用于解析 object_id、label、holder，不应无条件回填到 payload。
- 新对象只在 payload 明确引用且合法时创建。

### 3. possession / visibility 按第一条保留，可能漏掉新状态

位置：

- `backend/state_bridge.py`
- `normalize_state_dict()` 中 `possession_state` / `object_visibility` 去重逻辑

现状：

- possession 和 visibility 都按 `object_id` 去重。
- 当前逻辑是第一条 wins。

风险：

- 如果旧状态排在新状态前，新 holder 或 visibility 会被跳过。
- 物件转移、亮出、收起等明确变化可能漏写。

目标：

- 明确的新状态覆盖旧状态。
- 非法 holder、非法 object_id、非法 visibility 不能覆盖旧正常状态。
- 合并顺序应体现“旧状态兜底，新状态优先”。

### 4. `knowledge_scope` 缺少 schema 校验

位置：

- `backend/state_keeper.py`
- `validate_state_payload()`

现状：

- contract 中已经声明 `knowledge_scope`。
- prompt 中也要求 state keeper 输出 `knowledge_scope`。
- 但校验逻辑没有把 `knowledge_scope` 计入 recognized，也没有验证结构。

风险：

- 坏结构可能进入 normalize 或 actor registry。
- 只补知识的输出缺少明确校验路径。

目标：

- 增加 `knowledge_scope` 基本结构校验。
- 合法结构通过，坏结构被拒绝或清洗。

### 5. archive 刷新会重写旧窗口摘要

位置：

- `backend/keeper_archive.py`
- `backend/keeper_record_retriever.py`

现状：

- archive 不存在或需要刷新时，会从头构建所有窗口。
- 已有旧窗口会被重新摘要并保存。

风险：

- 同一历史窗口摘要可能漂移。
- 长期记忆不是 append-stable，而是 rebuild-stable。

目标：

- 默认只新增或 upsert 新窗口。
- 旧窗口除 force rebuild 或 archive 损坏外不重写。
- 避免重复 records 和历史摘要漂移。

### 6. `knowledge_records` 可能因同义改写膨胀

位置：

- `backend/actor_registry.py`
- `knowledge_records` 吸收 `knowledge_scope` 的合并逻辑

现状：

- `knowledge_records` 当前按 `(holder_actor_id, text)` 精确去重。
- 大模型可能用不同表述重复输出同一情报。
- 例如“主角知道村长是卧底”和“主角了解到村长的卧底身份”语义接近但文本不同。

风险：

- 长期知识库出现语义重复。
- selector 和 prompt 注入消耗增加。
- 旧知识被反复改写后形成噪声。

目标：

- Prompt 层要求 keeper 只输出从未出现过的全新情报。
- 代码层在同一 holder 下做轻量相似去重。
- 先使用清洗、关键词集合、字符 n-gram 或 Jaccard，不引入 LLM 归并。

### 7. object 缺少生命周期退出机制

位置：

- `backend/state_keeper.py`
- `backend/state_bridge.py`

现状：

- object patch 可表达 tracked、possession、visibility。
- 但缺少明确表达“消耗、摧毁、遗失、归档”的状态。

风险：

- 消耗品、被毁物件、花光的钱可能长期残留。
- 后续模型可能幻觉重新召唤已经不存在的物件。

目标：

- 引入 `lifecycle_status`: `active | consumed | destroyed | lost | archived`。
- 非 active 物件从 active object 层移除。
- 写入 `graveyard_objects`，保留物件已退出当前追踪层的事实。

### 8. archive upsert 需要感知 undo / rollback

位置：

- `backend/keeper_record_retriever.py`
- `backend/keeper_archive.py`

现状：

- 计划用 `window.end_pair_index` 作为 upsert key。
- 但如果玩家撤回或重试，当前有效 pair count 可能小于 archive 中已有 records。

风险：

- 被撤回的未来坏档仍留在 archive。
- retriever 可能召回已经不属于当前历史分支的 records。

目标：

- 每次 refresh / upsert 前按当前有效 `current_pair_count` prune。
- 删除 `window.end_pair_index > current_pair_count` 的 records。
- 再执行新增窗口 upsert。

### 9. possession 覆盖前需要明确 holder 合法性

位置：

- `backend/state_bridge.py`

现状：

- normalize 已有 `valid_holders` 概念。
- 但新状态覆盖旧状态时，需要明确合法边界，防止凭空 holder 覆盖旧正常状态。

风险：

- 模型幻觉出不存在的 NPC，导致关键物件被错误转移。
- object label 或系统化名字被误当 holder。

目标：

- 合法 holder 来源只包括当前人物、scene entity、actor registry 和 protagonist aliases。
- 非法 holder 的新 possession 不能覆盖旧合法 possession。
- `player_inventory`、`self` 等系统别名先归一到 protagonist，再判断。

### 10. schema 校验应采用 fail-safe coercion

位置：

- `backend/state_keeper.py`

现状：

- 计划增加 `knowledge_scope` schema 校验。
- 如果直接整包报错，可能导致本轮其它合法 patch 一起丢失。

风险：

- 大模型局部格式错误导致整轮 keeper 写入失败。
- 场景、物件等合法增量被不相关的 knowledge 格式问题拖累。

目标：

- 先 coercion，再 validation。
- 字符串 learned 自动转数组。
- 局部坏条目丢弃并记录 warning。
- 不因 `knowledge_scope` 局部坏结构拒绝整个 keeper patch。

## 修复目标

### 总目标

建立 keeper 写入质量稳定保证：

- 不重复写同一个内容。
- 脏数据不能覆盖正常数据。
- 明确发生的新内容不能漏写。
- 短期 delta 和长期账本职责分离。
- archive 历史窗口稳定，不因刷新漂移。

### 具体目标

1. `knowledge_scope` 改为严格本轮 delta。
2. `knowledge_records` 作为长期知识唯一落盘账本。
3. object patch 不再携带 baseline 全量对象。
4. possession / visibility 合并改为新明确状态优先。
5. `knowledge_scope` 增加 schema 校验。
6. archive refresh 改成窗口级 upsert。
7. `knowledge_records` 增加轻量相似去重。
8. object 增加生命周期退出与 `graveyard_objects`。
9. archive upsert 前 prune rollback 后的未来 records。
10. schema 清洗采用 fail-safe，不因局部坏字段丢弃整包。
11. 增加回归测试覆盖以上风险。

## 修改计划

### 阶段一：修复 `knowledge_scope` delta 语义

修改点：

- `backend/state_bridge.py`

修改内容：

- 移除 `normalize_state_dict()` 中对 `prev.knowledge_scope` 的长期合并。
- 当前 state 有合法 `knowledge_scope` 时，保留当前本轮 delta。
- 当前 state 没有 `knowledge_scope` 时，输出 `{}`，不继承上一轮。
- 增加 `_coerce_knowledge_scope()`，先清洗再落盘。
- state keeper prompt 明确要求只输出从未出现过的全新情报，重复旧信息必须省略。
- `knowledge_records` 保持现有长期保留逻辑。
- `knowledge_records` 吸收时按同一 holder 做轻量相似去重。

预期结果：

- `knowledge_scope` 不再重复携带旧知识。
- actor registry 只处理本轮新增知识。
- 长期知识仍在 `knowledge_records` 中稳定存在。
- 语义近似的旧知识不会持续膨胀长期知识库。

### 阶段二：修复 object patch 全量 baseline 污染

修改点：

- `backend/state_keeper.py`

修改内容：

- `_coerce_object_layers()` 保留 baseline index 用于查找和补 id。
- 不再因为 payload 使用 object 字段就把 baseline 全量对象写入 `normalized['tracked_objects']`。
- 只把 payload 明确提供的新对象或必要补建对象放入 payload。
- `_merge_keeper_fill()` 对 object 字段做增量合并，避免简单替换造成旧数据误覆盖或新数据漏写。
- 支持 `lifecycle_status`，识别 `consumed`、`destroyed`、`lost`、`archived`。
- 非 active 物件从 active object 层移除，并写入 `graveyard_objects`。

预期结果：

- 本轮 object patch 只表达本轮变化。
- baseline 旧对象不被无关 patch 重新强化。
- 新物件仍能合法创建并绑定。
- 物品消耗、摧毁、遗失后不会长期残留在 active objects。

### 阶段三：修复 object 状态覆盖顺序

修改点：

- `backend/state_bridge.py`

修改内容：

- `possession_state` 按 `object_id` 合并时，让 current 明确状态覆盖 prev。
- `object_visibility` 按 `object_id` 合并时，让 current 明确状态覆盖 prev。
- 非法 holder、非法 object_id、非法 visibility 不参与覆盖。
- 覆盖前校验 holder 是否存在于当前人物、scene entities、actor registry 或 protagonist aliases。
- 非法新 holder 不覆盖旧合法 holder。

预期结果：

- 物件转移不会被旧 holder 压住。
- 公开/私有变化不会被旧 visibility 压住。
- 脏状态不能覆盖正常状态。

### 阶段四：补充 `knowledge_scope` schema 校验

修改点：

- `backend/state_keeper.py`

修改内容：

- 增加 `_coerce_knowledge_scope()` 和 `_validate_knowledge_scope()`。
- `protagonist.learned` 为字符串时自动转数组。
- `npc_local.<name>.learned` 为字符串时自动转数组。
- 无法清洗的局部坏条目丢弃并记录 warning。
- 在 `validate_state_payload()` 中识别并校验清洗后的 `knowledge_scope`。

预期结果：

- 坏知识结构不会进入长期流程。
- keeper contract 与实际校验一致。
- 局部格式错误不会导致整轮其它合法 patch 被丢弃。

### 阶段五：archive refresh 改为窗口 upsert

修改点：

- `backend/keeper_archive.py`
- `backend/keeper_record_retriever.py`

修改内容：

- 保留 full rebuild 能力。
- 新增窗口级 upsert 刷新逻辑。
- 以 `window.end_pair_index` 作为 record key。
- 已存在旧窗口默认不重写。
- upsert 前删除 `end_pair_index > current_pair_count` 的未来 records。
- 仅新增当前历史增长后产生的新窗口。

预期结果：

- archive 不重复写同一历史窗口。
- 旧历史摘要不因刷新漂移。
- 撤回或重试后，未来坏档不会污染当前 archive。
- retrieval 使用的 records 更稳定。

## 测试计划

### 必补测试

1. `knowledge_scope` 不继承旧 delta。
2. 新 `knowledge_scope` 能写入 `knowledge_records`。
3. 旧 `knowledge_records` 不被覆盖。
4. object patch 不回填 baseline 全量对象。
5. 新 possession 覆盖旧 possession。
6. 非法 possession 不覆盖旧合法 possession。
7. 新 visibility 覆盖旧 visibility。
8. 非法 visibility 不覆盖旧合法 visibility。
9. archive refresh 不重复 records。
10. archive refresh 不重写已存在旧窗口。
11. 同义改写的旧知识不会新增重复 `knowledge_records`。
12. object `consumed` / `destroyed` 会退出 active object 层并进入 `graveyard_objects`。
13. archive rollback 后会 prune 未来 records。
14. `knowledge_scope` 局部坏结构不会导致整包失败。

### 建议运行命令

```bash
pytest tests/test_state_fragment.py
pytest tests/test_keeper_record_retriever.py
pytest tests/test_keeper_contract.py
```

如时间允许，再跑：

```bash
pytest tests/test_keeper_*.py tests/test_state_fragment.py
```

## 验收标准

修复完成后应满足：

- 空 keeper patch 不清空旧数据。
- `knowledge_scope` 只保留本轮新增，不长期累积。
- 长期知识只通过 `knowledge_records` 保存。
- 同一知识不会每轮被当作新增重复处理。
- 同义改写的同一知识不会造成长期知识库膨胀。
- object patch 不携带无关 baseline 全量对象。
- destroyed / consumed / lost 物件不会继续作为 active tracked object 注入。
- 新 holder 明确覆盖旧 holder。
- 新 visibility 明确覆盖旧 visibility。
- 非法 holder、坏 object label、非法 visibility 不能覆盖正常数据。
- archive refresh 不重复、不漂移旧窗口。
- archive 在 undo / rollback 后不会保留未来 records。
- 新增回归测试全部通过。

## 稳定性保证边界

本修复能保证 keeper 写入链路中的合并、过滤、去重和长期落盘边界更稳定。

不能保证模型永远不输出脏内容，因此稳定性依赖三层防线：

- prompt 约束：减少模型产生脏 patch。
- payload coercion / validation：拒绝或清洗坏结构。
- normalize / merge：防止坏 patch 覆盖旧正常状态。

修复完成后，即使 state keeper 输出弱信号、空列表、旧知识或局部 object patch，也应尽量被限制在本轮增量范围内，不影响长期稳定账本。
