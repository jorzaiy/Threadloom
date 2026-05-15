# Threadloom Review

**当前版本：v1.0**

> 历史评审快照：本文记录 2026-04-16 左右的质量判断与阶段性配置，不保证所有模型名、默认 preset 或运行参数仍等同于当前 live 配置。当前运行入口以 `README.md`、`doc/API.md`、`doc/BACKEND.md`、`doc/OPERATIONS.md` 和实际配置文件为准。

## 当前判断

`Threadloom` 现在已经具备最小闭环，不再只是设计稿：
- Web 前端可访问
- 后端 HTTP API 可用
- narrator 已接真实模型
- session-local `history / state / summary / persona` 已写回
- opening、partial regenerate、session lifecycle 都已有代码路径

但它仍然是原型，离“稳定主链”还有明显距离。问题不在于能不能跑，而在于：事实层是否足够稳、fallback 是否足够保守、连续多轮后会不会轻微漂移累积成明显失真。

## 2026-04-16 Live HTTP Soak

这轮新增了一次真实 HTTP 长跑验证，重点不再是“链路能不能跑”，而是：

- 开局选择是否正常落到 runtime 主链
- 世界书与系统级 NPC 候选是否真的进入 narrator prompt
- `12` 对 recent window 是否真的作为 narrator 主上下文
- keeper archive 是否会在窗口外真实回流
- 长跑后 state / threads / important_npcs 是否出现明显漂移

已确认通过：

- `new-game -> opening -> 选局 -> narrator -> state_keeper` 全链真实可跑
- 系统级 NPC 候选真实进入 prompt
- 世界书预算化注入真实进入 prompt
- `12` 对 recent window 已真实生效
- keeper archive 在记录真正掉出 recent window 后，会以 `【较早结构记录】` 真实回流到 narrator prompt
- HTTP 层已修：客户端提前断开时不再把已完成请求伪装成 `500`，只记录轻量断连日志

本轮暴露的主要残余问题：

- 实体归一化仍有噪声，主要体现在动态场景中同一群体/剪影类称呼可能并存：
  - `毡笠人 / 毡笠身影`
  - `暗影 / 皂衣人`
- 这类问题当前更像 scene entity merge 与 important NPC alias 过滤不够保守，而不是 narrator 主链本身失效

## 2026-04-16 Clean Session Regression

这轮后续又新增了两组“从现有剧情 history 派生干净测试 session，再跑真实 HTTP 回归”的验证。

目标：

- 避开旧 session 已落盘的脏 state
- 验证“脚本候选 + LLM 判定”的通用实体恢复策略是否能在 live 写回里压住垃圾名字
- 确认这条路径不是只对单一角色卡有效

当前结论：

- judge 驱动的通用实体恢复路径已在 `碎影江湖` 的干净 session 真实回归里证明有效
- `血蚀纪` clean session 的真实 HTTP 回归也已通过：世界书未注入模板垃圾，抽象机制词未再进入人物池
- 在 `碎影江湖` clean session 上，原先的：
  - `三处私盐`
  - `可真正先`
  - `这句话真`
  - `笠人`
  这类垃圾名字已被显著压制

跨题材状态：

- `血蚀纪` clean session 当前未再复现抽象机制词误入人物池
- `scene_entities / important_npcs / relevant_npcs / continuity_candidates` 在 4 轮真实 HTTP 回归里都保持干净

仍需继续观察的点：

- judge 路径当前已补上“抽象概念 / 系统机制词误入人物池”的通用过滤，但仍需继续观察跨题材长跑稳定性
- 对真正相似别称的稳定归并（例如“毡笠人 / 毡笠身影”）仍需继续依赖 keeper / merge 层规则
- active_threads 近期暴露过“旧 risk key 挂新 label”的 continuity 错位问题；现已改为主要继承 `thread_id`，避免旧线程名残留到新内容上
- narrator 对“过渡态场景”的输出近期有越写越短的趋势；现已补轻约束，要求即使是回屋、关门、烧水、换位等桥段，也要给出具体环境变化、人物反应、动作后的余波或正在累积的细节变化，但不为了“有戏”而每轮硬塞危险感
- narrator 当前额外补了一层目标导向：维持一个会自己流转的 RP 世界，主角是参与者与观察者，而不是唯一驱动器
- active_threads 目前已开始使用本地 `thread label composer`，把 `main thread` 从“暴露风险”这类抽象标签收回到更可演的当前局势描述
- 上游名字过滤已补一层通用“语气副词 / 形容词碎片”拦截，避免 `笑嘻嘻 / 淡淡 / 轻轻` 这类词继续混入 `scene_entities / relevant_npcs / important_npcs`

## 当前主优点

当前这套原型比旧 transcript-first 链路更好的地方：
- `runtime-rules / state / summary` 的优先级已经明显高于纯 transcript 惯性
- session-local 写回已经落地，不再直接把在线会话当唯一真相源
- opening 已经独立成状态机，而不是把“开始游戏”当普通用户输入
- partial reply 已被隔离，不再直接污染后续 state、历史展示或下一轮 narrator recent window
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
- 调试浮动面板已更新为展示 prompt block、selector/event recall、state keeper diagnostics、世界书注入体量和状态快照侧的 NPC / active object / signal 层；`active_threads` 不再作为默认用户可见主面板项目
- 玩家设定已改为“自然语言源文本 -> State Keeper 模型整理 -> 固定统一 JSON -> prompt preview”的编辑流程；高级用户仍可改 JSON 内容，但 schema 结构由后端校验保护
- `state_keeper.py` 现在已加入低信号拒收和相对上一轮 state 的回归检查
- `state_updater.py` 现在更偏保守继承，减少弱推断覆盖强状态
- `state_fragment` 已前移到主链，并在 `state_keeper` 失败时形成 `fragment-baseline -> heuristic fallback` 的双层兜底
- `runtime.json` 里的 `default_debug / show_debug_panel / history_page_size` 已贯通到 API 与前端
- 对已污染的旧 session，现已验证可通过离线重建方式直接把主状态从旧开局壳拉回当前剧情
- 前端默认会话选择已改为最近更新会话优先；旧的 `story-live` 不再应默认抢占入口
- 设置中的角色卡管理已改为动态读取角色卡元数据与缩略封面，不再直接吃原始大图
- narrator 输入层已加入更通用的信息边界提示，不再只针对“主角独知观察”做窄补丁
- `README.md`、`API.md`、`OPERATIONS.md` 已改为反映当前代码现状，而不是旧草图

## 当前仍然最关键的问题

### 1. `state_keeper` 已切换为 `gemma-4-31b-it` 双 keeper 架构

原来的最大瓶颈（纯 prose 反提 + 4B 模型能力不足）已基本解决。

现状：
- skeleton + fill 双 keeper 均使用 `gemma-4-31b-it`，提取 prompt 已加入字段级质量指南和正反例
- `state_keeper_candidate` 现继承 State Keeper 模型，默认上限已高于早期 280 截断阶段
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
- state snapshot 已直接提供前端可展示的实体列表，名字反查问题已基本解决
- 剩余问题是同名实体的交互式 disambiguation 仍不完整；当前策略是保守展示、不给可能错误的详情入口

### 5. web 配置到 UI 的映射已基本打通

当前已打通：
- `default_debug`
- `show_debug_panel`
- `history_page_size`
- `show_state_panel`

影响：
- 已接通的配置现在真的会改变前端行为

结论：
- 当前这一层主要剩余工作转为减少无效配置项与补文档，而不是继续补 UI 接线

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
- `state_bridge.py` 只保留本轮 `knowledge_scope` delta，不再长期合并旧 scope
- `actor_registry.py` 将本轮 `knowledge_scope` 派生为 actor-id 版长期 `knowledge_records`，并做轻量相似去重
- `narrator_input.py` 将结构化知情边界渲染为 narrator 可消费的格式
- 已从纯文本知情边界规则升级为结构化 + 文本混合方案

影响：
- NPC 知情边界不再完全依赖 prompt 和模型自觉，而有独立数据结构支撑
- 新登场 NPC 的知情范围现在可以通过 `npc_local` 结构显式约束

残余风险：
- 复杂多 NPC 场景中的知情推理仍可能被 narrator 模型忽略
- `knowledge_scope` 的实际效果仍需更多长对话验证

## 2026-05-07 NPC profile / persona 长跑检查

针对 `bd4769` 的 narrator / keeper / selector 检查结论：summary chunk 的第二段按固定 12 轮窗口应在 `13-24` 后生成，`turn 23` 仍只有 `chunk_0001 / 1-12` 属正常现象。真正暴露的问题是 NPC 详情层和召回层：

- selector 已能识别 NPC profile targets，但 source profile 缺失时 narrator `npc_profile_count` 仍为 0。
- session persona longterm 文件虽然已晋级并更新重要度计数，但人格 hooks 和剧情观察长期停在骨架状态。
- keeper archive 中程 digest 有窗口记录，但部分 `time_anchor / location_anchor / ongoing_events / npc_registry` 信息密度偏低。
- 当前事件中相关但未站在前台的人物容易从 `relevant_npcs` 消失，影响后续 selector 召回。

本轮已收紧：

- source NPC profile 缺失时，`context_builder.load_npc_profiles()` 回落到当前 session persona seed，并把身份、hooks、observations 格式化为 narrator profile。
- `persona_updater` 开始把近期 assistant 叙事中的 NPC 相关片段写入 `observations`；不读取用户 prompt 原文，不重复放大同一观察片段。
- keeper archive heuristic digest 接入 NPC registry，并更积极从窗口正文提取具体事件锚点。
- `state_bridge` 会在 `main_event` / continuity 文本中保留有证据的非 onstage 稳定人物为 `relevant_npcs`。

仍需继续观察：persona observation 当前是轻量片段，不是完整 LLM 人物小传；它用于补足 narrator profile 断链，不应替代角色卡、system NPC source 或 actor registry。

## 2026-05-07 实名揭示 alias-upsert

`8c94e5` 继续测试时发现：NPC 已在 narrator 正文中自报姓名或被点名，但 state 仍保留旧 generic actor，例如“剃寸头的高个子学员”没有绑定为“秦野”，“迟到新生”没有绑定为“赵明”。

根因是 actor registry 为保护基础设定采取“只创建新 actor，不修改已有 actor”的策略，导致实名只进入 `knowledge_records / risk / main_event` 文本，未绑定回 actor alias。

本轮补最小正确修复：

- 只在 narrator 正文出现明确实名揭示时触发，例如“姓秦。秦野。”或“赵——赵明。”。
- 只在上下文能唯一匹配已有 generic actor 时追加 alias。
- 不改写 actor 原始 `name / personality / appearance / identity`，避免破坏不可变基础设定。
- alias 更新会刷新 `actor_context_index.last_mentioned_turn`，并让后续 `knowledge_scope.npc_local.<实名>` 能绑定到已有 actor_id。

这不是通用重命名系统，仍需继续观察复杂多人同场、多个 generic actor 同时自报姓名时的歧义处理。

## 建议的下一步优先级

## 2026-05-06 维克托 session 0bfef1 观察记录

- 观察到 narrator 在安全/权威机构反制时容易过于完美化：安全组可以发现异常，但不应默认一步拿到完整、无争辩空间的证据链。
- 暂不修改 narrator prompt；先更换 narrator/keeper 相关 LLM 后继续观察。
- 后续若仍复现，考虑约束反制节奏为“怀疑 → 试探 → 施压 → 证据”，给玩家保留解释、装傻、交易或转移风险的 RP 空间。

1. **narrator_input block 顺序对齐 v1.0 规范** — 硬锚点和人物连续性表应前移
2. ~~**实时消息处理添加 429 重试**~~ — ✅ 已完成：`model_client.py` 和 `local_model_client.py` 均已加入 `_retry_on_rate_limit` 装饰器（429/503 指数退避，最多 3 次，尊重 `Retry-After`）
3. **世界书预算参数暴露到 runtime.example.json** — 让用户可配置
4. **keeper archive 反向引用** — keeper 决策时参考历史 archive 记录
5. ~~**knowledge scope 系统**~~ — ✅ 已完成：`knowledge_scope` 字段已落地到 state，含 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`；当前语义为本轮 delta，长期知识由 `knowledge_records` 保存并去重，再由 narrator_input 渲染
