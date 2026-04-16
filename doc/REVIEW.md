# Threadloom Review

## 当前判断

`Threadloom` 现在已经具备最小闭环，不再只是设计稿：
- Web 前端可访问
- 后端 HTTP API 可用
- narrator 已接真实模型
- session-local `history / state / summary / persona` 已写回
- opening、partial regenerate、session lifecycle 都已有代码路径

但它仍然是原型，离“稳定主链”还有明显距离。问题不在于能不能跑，而在于：事实层是否足够稳、fallback 是否足够保守、连续多轮后会不会轻微漂移累积成明显失真。

## 当前主优点

当前这套原型比旧 transcript-first 链路更好的地方：
- `runtime-rules / state / summary` 的优先级已经明显高于纯 transcript 惯性
- session-local 写回已经落地，不再直接把在线会话当唯一真相源
- opening 已经独立成状态机，而不是把“开始游戏”当普通用户输入
- partial reply 已被隔离，不再直接污染后续 state
- arbiter、threads、important NPC、persona 这几层已经开始进入统一主链
- narrator / turn_analyzer / state_keeper 已具备分模能力，而不是全部绑死在一套模型配置上

## 这轮收紧的内容

本轮额外收紧了几处会直接影响稳定性的低风险问题：
- `bootstrap_session.py` 不再靠 `canon` 文本内容判断“是否已初始化”，而是按 session-local 文件是否存在判断，降低重复 bootstrap 风险
- `handler_message.py` 现在支持首轮直接输入数字/标题/`随机开局` 进入 opening choice 分支，不必先看一轮菜单
- opening 菜单未选定时，错误输入不会误入正常 runtime 主链，而是继续停留在 opening guard
- 已进入开局后再次输入开局命令时，guard 回复现在也会写入 history，避免界面和历史不一致
- `server.py` 为 `POST /api/message`、`new-game`、`delete-session`、`regenerate-last` 增加了 session 级串行锁，降低同一 session 并发写冲突
- `regenerate_turn.py` 回滚幂等缓存时改为按 `turn_id` 清理，而不是盲删最后一个缓存项
- `frontend/app.js` 在切换 session、刷新、新游戏、删除后会重置 entity/detail/debug 侧栏，避免残留旧会话信息
- state snapshot 现在由后端直接提供 `onstage_entities / relevant_entities`，前端不再用名字反查 `entity_id`
- `frontend/app.js` 对同名实体采取保守策略：若存在多个同名实体，前端不再给出可能错误的详情入口
- `state_keeper.py` 现在已加入低信号拒收和相对上一轮 state 的回归检查
- `state_updater.py` 现在更偏保守继承，减少弱推断覆盖强状态
- `state_fragment` 已前移到主链，并在 `state_keeper` 失败时形成 `fragment-baseline -> heuristic fallback` 的双层兜底
- `runtime.json` 里的 `default_debug / show_debug_panel / history_page_size` 已贯通到 API 与前端
- 对已污染的旧 session，现已验证可通过离线重建方式直接把主状态从旧开局壳拉回当前剧情
- 前端默认会话选择已改为最近更新会话优先；旧的 `story-live` 不再应默认抢占入口
- 角色卡侧栏已改为动态读取角色卡元数据与缩略封面，不再直接吃原始大图
- narrator 输入层已加入更通用的信息边界提示，不再只针对“主角独知观察”做窄补丁
- `README.md`、`API.md`、`OPERATIONS.md` 已改为反映当前代码现状，而不是旧草图

## 当前仍然最关键的问题

### 1. `state_keeper` 已切换为 `gemma-4-31b-it` 双 keeper 架构

原来的最大瓶颈（纯 prose 反提 + 4B 模型能力不足）已基本解决。

现状：
- skeleton + fill 双 keeper 均使用 `gemma-4-31b-it`，提取 prompt 已加入字段级质量指南和正反例
- skeleton keeper `max_output_tokens` 调高至 280，配合截断 JSON 补全 fallback，LLM 成功率 93%+
- heuristic 层重写为评分式架构：`_score_sentence()` 替代关键词猜世界，加入元文本过滤和中文自然断点截断
- 在 4 组跨题材长记录测试中（维克托、九幽大陆、血蚀纪），关键指标全部归零

残余风险：
- narrator prose 漂移仍会影响 LLM keeper 输出质量，但影响程度已大幅降低
- 极端长对话（1000+ 轮）的累积漂移尚未充分验证

### 2. fallback state 质量已大幅提升

`state_updater.py` 已重构为基于评分的抽取架构，不再依赖题材关键词猜世界。前面有 `fragment-baseline` 兜底，heuristic 层也已加入元文本过滤、中文自然断点截断和阈值过滤。

影响：
- 当 `state_keeper` 失败时，fallback 产出质量已接近可用水平
- 在 4 组跨题材长记录测试中，Time∅ 0%、Loc∅ 0%、Event⚠ 0%、Drift 0

结论：
- fallback 已从保命进入基本可靠阶段
- 仍不如 LLM keeper 精确，但不再是明显短板

### 3. 重要人物 / 线程 / summary 之间仍会互相放大弱信号

目前这三层都已经进入主链，但耦合也更强了。

当前改进：
- thread tracker 已从统一 `THREAD_RETENTION_TURNS` 改为按类型分级的 `THREAD_RETENTION_CONFIG`（main:4, risk:3, clue:2, arbiter:1）
- 新增 `cooling_down` 中间态：线程不再直接从 watch 跳到移除，而是经过 `active → watch → cooling_down → resolved → archived` 的完整状态机
- 已解决线程会归档到 `state.resolved_events[]`（最多保留 20 条），不再只依赖 summary 保存
- memory 评分层已增强：`_score_pair()` 加入时间衰减、NPC 关系权重、重复惩罚；`_heuristic_digest()` 重写为通用 `_score_events()` + `_score_open_loops()` 架构
- `keeper_record_retriever._score_record()` 已加入时间衰减因子
- `build_memory_bundle()` 现在接受可选 `important_npcs` 参数

影响：
- 弱信号放大链已被部分打断：线程退出更精细，记忆评分更考虑时效性和重复度
- 一次性服务 NPC 偶发高估仍没有完全根治，但影响面已收窄

结论：
- 需要继续收紧 retained 条件和降权条件
- 尤其要盯“连续互动”和“承载主推进”的证据门槛

### 4. 同名实体仍缺完整 disambiguation

本轮已经把实体展示结构前移到后端，前端不再名字反查；但交互上仍只是保守展示，没有完整 disambiguation UI。

影响：
- 至少不会误点到错误实体
- 但还没有真正的同名实体区分交互

结论：
- 这是小问题，但会持续影响可观察性
- 后续应让 state snapshot 直接给前端可展示的 `entity_id + display_name + short role` 列表，而不是前端再拿名字回查

### 5. web 配置到 UI 的映射已打通，但还不完整

当前已打通：
- `default_debug`
- `show_debug_panel`
- `history_page_size`

但还没打通：
- `show_state_panel`

影响：
- 已接通的配置现在真的会改变前端行为
- 但仍有一部分配置停留在“有定义、未消费”的状态

结论：
- 下一步要么继续把 `show_state_panel` 接到布局层
- 要么删掉未消费配置，避免假配置继续积累

### 6. 主角 runtime 仍缺位；事件归档层已初步落地

当前系统已经开始把 NPC、线程和摘要分层，主角仍缺独立层，但已解决事件归档已有初步结构。

已完成：
- thread tracker 已补 `resolved_events` 归档：线程经 `cooling_down` 过渡后进入 `resolved`，归档到 `state.resolved_events[]`（最多 20 条）
- 已解决事件不再只依赖 summary 和记忆层保存，而有显式的结构化归档

仍缺位：
- 主角 observer / user-side 信息若污染到 NPC 层，后续会被 `important_npcs`、threads、summary 一起放大

结论：
- 后续应补 `protagonist_runtime`
- `resolved_events` 已初步可用，后续可继续优化归档内容的丰富度

### 7. NPC 间信息隔离已升级为结构化 knowledge scope

当前系统已经从纯 prompt 软约束升级为结构化 + 文本混合的知情边界管理。

已完成：
- state 中新增 `knowledge_scope` 字段，独立追踪 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`
- fill prompt 已指导 keeper 按回合提取知识增量
- `state_bridge.py` 中的 `_merge_knowledge_scope()` 负责增量合并（去重，主角上限 30 条，单 NPC 上限 15 条）
- `narrator_input.py` 中的 `_format_knowledge_scope()` 将结构化知情边界渲染为 narrator 可消费的格式
- 已从纯文本知情边界规则升级为结构化 + 文本混合方案

影响：
- NPC 知情边界不再完全依赖 prompt 和模型自觉，而有独立数据结构支撑
- 新登场 NPC 的知情范围现在可以通过 `npc_local` 结构显式约束

残余风险：
- 复杂多 NPC 场景中的知情推理仍可能被 narrator 模型忽略
- `knowledge_scope` 的实际效果仍需更多长对话验证

## 建议的下一步优先级

1. **narrator_input block 顺序对齐 V0.3 规范** — 硬锚点和人物连续性表应前移
2. ~~**实时消息处理添加 429 重试**~~ — ✅ 已完成：`model_client.py` 和 `local_model_client.py` 均已加入 `_retry_on_rate_limit` 装饰器（429/503 指数退避，最多 3 次，尊重 `Retry-After`）
3. **世界书预算参数暴露到 runtime.example.json** — 让用户可配置
4. **keeper archive 反向引用** — keeper 决策时参考历史 archive 记录
5. ~~**knowledge scope 系统**~~ — ✅ 已完成：`knowledge_scope` 字段已落地到 state，含 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`，并已接入 keeper 提取、state_bridge 合并和 narrator_input 渲染
