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

## 2026-05-19 Unified Memory Transaction

本轮针对 `九幽大陆-20260517-f12610` 暴露的长 session 记忆混乱做了第一阶段收口。结论是：原始 `history.jsonl` 相对干净，主要污染来自多个派生记忆层各自调用 LLM 后互相竞争事实解释权，例如 summary chunk 人名漂移、keeper archive 把后期全局物件写进早期窗口、物件 ID 重复，以及 keeper 输出被 `finish_reason=length` 截断后仍被视作成功。

已完成的第一版纵切：

- 默认启用统一记忆事务：每个完整 runtime 回合只让 full `state_keeper` 作为唯一 LLM 记忆 patch 来源。
- 统一模式下关闭 skeleton keeper LLM、actor registry LLM、focused possession retry LLM、event ledger LLM、summary chunk LLM。
- `state_keeper` 的 `finish_reason=length` 视为失败，不允许半截输出落盘。
- summary chunk LLM 若被截断，降级 heuristic 并记录 `llm_rejected_reason=length`。
- context 装配前 quarantine 明显主角名复合漂移的 summary chunks，避免坏 chunk 继续注入 narrator。
- keeper archive heuristic digest 只允许记录当前窗口文本中实际出现的物件，避免用最新全局物品污染早期窗口。
- opening choice 首轮进入 narrator 时跳过中间 checkpoint save，最终 state 由 handler 在本轮结束统一提交。
- `repair_memory(rebuild_derived=True)` 会清空并 heuristic 重建 summary chunks，同时无 LLM 重建 keeper archive；已用于修复 f12610 的派生缓存。

验证结果：相关 changed files LSP clean；memory / context / keeper / delete 回归扩展集合 `178 passed`；针对 review blocking 的 opening / event ledger / summary chunk focused tests `9 passed`；targeted Oracle follow-up review 通过。

仍建议观察 5-10 个真实回合后再继续 Phase 3 完整版：也就是更大的 `merge_candidate` schema、evidence quote required、stable ID resolver、duplicate reject / alias merge / unresolved queue。当前版本已切掉最大污染源，但尚未实现完整的候选合并审批队列。

### 2026-05-21 Profile Detail Recall, Object Lifecycle, and Test Cleanup

本轮继续收紧长 session 中“旧资料过量注入”和“物件生命周期误判”的问题，并清理了几份不会被正常 pytest 维护的 live/manual 脚本。

已完成：

- 玩家档案常驻 prompt 继续保持 slim，只保留公开身份、可见外貌、稳定能力、性格和偏好等低干扰摘要；背景、心理、世界适配和私密边界被拆成 selector 可检索的 profile detail section，只有本轮出现身世回忆、能力使用、外貌检视、身份挑战或私密边界等强锚点时才注入 `【命中玩家档案细节】`。
- `【命中玩家档案细节】` 明确标注为资料数据而非指令，且 `private / narrator_only` 内容不会自动变成 NPC 已知事实；turn trace 中该块会被 redacted，只保留 prompt block size 统计，避免调试 artifact 暴露私密资料。
- 事件索引召回改为 selector 命中后才进入 `【命中事件索引】`；若 event hit 已覆盖同一主题，宽泛 summary chunk 会被压制，低压休息、等待、移动等弱动作不会单独拉回旧压力摘要。
- 物件 lifecycle 增加“持有声明优先”保护：同一轮 payload 若仍声明某物有 holder、status 或 location，就不能同时把该物标为 `lost / archived` 并移入 `graveyard_objects`；`consumed / destroyed` 仍按明确消耗或销毁处理。
- 删除 obsolete live/manual test scripts：`tests/test_model_comparison.py`、`tests/test_model_compare_simple.py`、`tests/test_skeleton_impact.py`、`tests/test_selector_quality.py`。这些脚本依赖本地 HTTP 服务、会改配置或使用旧 session 路径，不属于当前可重复 pytest 回归集。

验证：`python3 -m pytest --collect-only -q` 成功收集 `350` 个测试；`python3 -m pytest -q` 结果为 `348 passed, 1 skipped, 1 failed`，唯一失败仍是既有的 `test_user_profile_route_uses_multi_user_context_before_loading_profile`，与本轮脚本删除和 lifecycle/profile recall 修改无关。

### 2026-05-19 Actor Persona Hooks

后续针对 NPC 性格、行为模式和语言特点的持续性做了补强：统一记忆事务模式下，NPC 表达层人格不再由 display-name keyed `persona_updater` 每轮启发式写回，而是纳入同一次 full `state_keeper` LLM 输出。

当前边界：

- 新增 `persona_patches`，只允许为既有非主角 `actor_id` 写表达层钩子：语气、行为模式、决策偏好、习惯动作、受压反应、证据和置信度。
- `persona_patches` 必须带 `display_name`，且必须与 actor registry 中该 `actor_id` 的 `name / aliases` 精确匹配；未知 actor、主角、名称不匹配或宽泛子串匹配都会被丢弃。
- hook 文本会被压成单行描述，并清除 prompt block 标记、控制字符和明显指令式片段；narrator 渲染时也会再次清洗，避免 LLM 派生文本变成新 prompt 指令。
- `state.actor_persona_hooks` 按 actor_id 注入 `【角色注册表】`，只约束同一 actor_id 的表达和行为倾向，不代表人物当前在场，也不能覆盖姓名、身份、外貌等不可变基础设定。
- 旧 session persona seed 仍可作为 NPC profile fallback 读取，但 unified 模式下不再自动进入 `【NPC 表现层人格】`，避免旧 display-name 记忆继续影响当前 actor-id 绑定人格。

验证：persona / memory / narrator / context / actor / regenerate targeted suite `162 passed`，五路 review 后补上了旧 persona 注入隔离、persona hook prompt-injection 清洗、display_name 强校验和对应回归测试。

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

### 1. `state_keeper` 已切换为双 keeper 架构

原来的最大瓶颈（纯 prose 反提 + 4B 模型能力不足）已基本解决。

现状：
- skeleton + fill 双 keeper 均使用当前配置的 State Keeper 模型，提取 prompt 已加入字段级质量指南和正反例
- `state_keeper_candidate` 现继承 State Keeper 模型，默认上限已高于早期 280 截断阶段
- heuristic 层重写为评分式架构：`_score_sentence()` 替代关键词猜世界，加入元文本过滤和中文自然断点截断
- 在 4 组跨题材长记录测试中（维克托、九幽大陆、血蚀纪），关键指标全部归零

残余风险：
- narrator prose 漂移仍会影响 LLM keeper 输出质量，但影响程度已大幅降低
- 极端长对话（1000+ 轮）的累积漂移尚未充分验证

### 2. fallback state 质量已大幅提升

在线主链失败时优先形成 `fragment-baseline` 兜底；`state_updater.py` 已重构为离线 replay / rebuild 可用的保守抽取架构，不再依赖题材关键词猜世界。heuristic 层也已加入元文本过滤、中文自然断点截断和阈值过滤。

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

### 6. 主角 runtime 已初步落地；事件归档层已初步落地

当前系统已经开始把 NPC、线程和摘要分层；主角已作为 actor registry 内置 protagonist 与玩家档案分层进入 runtime，但 observer/主角信息仍需要继续和 NPC 层做强隔离。事件归档已有初步结构。

已完成：
- thread tracker 已补 `resolved_events` 归档：线程经 `cooling_down` 过渡后进入 `resolved`，归档到 `state.resolved_events[]`（最多 20 条）
- 已解决事件不再只依赖 summary 和记忆层保存，而有显式的结构化归档

仍需继续收紧：
- 主角 observer / user-side 信息若污染到 NPC 层，后续会被 `important_npcs`、threads、summary 一起放大

结论：
- 后续应继续收紧 protagonist / NPC 信息边界
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

## 2026-05-16 header-only main_event 误判修复 + state_keeper 清理

### 问题

session `0a1f32` 中 `main_event` 和 thread label 反复出现"只有时间+地点、没有事件内容"的情况，例如：

```
景元三百二十七年四月初四，上午，青石驿站院子里。
```

### 根因

`state_fragment.py` 的 `_looks_like_header_only_sentence()` 和 `state_bridge.py` 的 `_looks_like_header_only_event()` 使用简单子串匹配检测动词，地名中的字（如"驿站"的"站"）被误判为动词"站"，导致函数认为句子包含动作，放行了纯标头句子。

问题传播链：
1. narrator 回复以场景标头开头
2. `extract_reply_skeleton()` 提取第一句作为 main_event 候选
3. `_looks_like_header_only_sentence()` 误判放行
4. 错误的 main_event 写入 state_fragment → baseline_state
5. state_keeper fill 模式不覆盖已有 main_event → 错误值保留
6. `thread_tracker` 用 main_event 覆盖 thread label

### 修复

将两个函数的判断逻辑从反向（"没有动词 → 是 header"）改为正向（"所有非时间 part 都匹配地点模式 → 是 header"），并增加主语代词排除。

### state_keeper.py 清理

同时清理了 `state_keeper.py` 中因反复修改积累的问题：

| 问题 | 修复 |
|------|------|
| `_validate_knowledge_scope` 变量作用域 bug：内层 for 循环缩进错误，只验证最后一个 NPC 的 learned | 修正缩进 |
| `STATE_KEEPER_SYSTEM`（旧版 prompt）完全未被引用 | 删除 |
| try/except 后不可达 `break` | 删除 |
| `_descriptor_signature` wrapper 从未被调用 | 删除 |
| `_coerce_state_payload` 和 `_merge_keeper_fill` 双重 derive signals→risks/clues | 移除冗余 derive |
| `call_skeleton_keeper` 中 `_skeleton_user_prompt()` 被调用两次 | 存入变量 |

所有 235 个测试通过。

---

## 2026-05-27: narrator conjecture guard 误判修复 + onstage_npcs 丢失修复

### narrator conjecture-to-history guard 误判

**问题**：session `九幽大陆-20260520-e23032` turn-0149 生成失败，4 次重试全部被 `unsupported_conjecture_to_history_assertion` 拒绝。

**根因**：用户输入中包含角色对话问号（"师兄，几天没吃饭了？"），触发 `user_is_conjecture = True`。conjecture 分支的 3 句滑动窗口只要求 `PRIOR_EVENT_ASSERTION_MARKERS`（如"已经"），不要求 `PRIOR_EVENT_TEMPORAL_MARKERS`（如"之前/昨天"）。narrator 回复中"铜筹已经在空中动了"被误判为编造历史事件。

**修复**：conjecture 分支的 window 检查增加 `PRIOR_EVENT_TEMPORAL_MARKERS` 要求，与主分支逻辑一致。只有同时包含时间词和断言词的窗口才会触发拒绝。

### onstage_npcs 偏窄/丢失

**问题**：最近 15 轮中 `state_after_keeper.onstage_npcs` 频繁为空，即使场景中有多个 NPC 在场。

**根因**：
1. Keeper LLM 输出 dict 格式的 onstage_npcs（`{entity_id, primary_label, ...}`），但 normalize/merge 阶段对每个 item 做 `str(item)` 转换，dict 变成无效字符串后被丢弃
2. 上限"最多 3 个"过于严格，实际场景常有 4-5 人同时在场

**修复**：
1. normalize 和 merge 阶段兼容 dict 格式，提取 `primary_label`/`name`
2. 上限从 3 放宽到 5（prompt + 代码）
3. 安全网：keeper 输出为空时回退到 state_fragment 的值

---

## 2026-05-27: selector bigram 召回修复 + knowledge_scope 拥挤修复

### Selector 关键词匹配失败

**问题**：session e23032 turn-0198 narrator 输出"路牌两枚，各五文，共十文"，与 turn-0186 已建立的"路牌要一百二十文"矛盾。

**根因链**：
1. `_topic_tokens` 使用 `{2,8}` 贪婪 regex 匹配连续中文字符，8 字上限导致 "路牌" 被切断在 token 边界（"衣书吏申办两个路" + 逗号 + "同时…"）
2. 即使不被切断，长 token 之间几乎不可能跨上下文匹配（"子为何没路牌" ≠ "申办两个路牌"）
3. turn-0186 的 event_summary 分数为 0，完全无法被 selector 召回

**修复**：
- `_topic_tokens` regex 改为 `{2,}` 不限上限（按标点自然断句），只保留 ≤8 字的原始 token，但对所有 3+ 字 segment 生成 bigram sub-token
- Bigram 评分权重降低（shared: 0.25, current: 0.5），防止噪音
- `weak_mundane_query` 和 `carryover-only` 过滤条件要求 3+ 字 token 才算有效匹配

### Knowledge_scope 被物品持有状态挤占

**问题**：keeper 正确提取了 "黑脸小子因家里穷凑不齐一百二十文路牌钱" 到 `knowledge_scope.protagonist.learned`，但该记录从未出现在 `knowledge_records` 中。

**根因**：`_add_lightweight_knowledge_delta` 每轮把物品持有状态追加到 `knowledge_scope.protagonist.learned`，然后 `[-10:]` 截断把 keeper 提取的关键知识挤掉。到 `update_actor_registry` 转写 `knowledge_records` 时，信息已丢失。

**修复**：`_add_lightweight_knowledge_delta` 直接写入 `knowledge_records`，不再经过 `knowledge_scope` 中间层，避免与 keeper 输出竞争配额。

## 2026-05-30: 地基收紧 —— 测试地雷、store loader、并发锁、server 路由分发

本轮不改 runtime 行为，只针对外部审查指出的“实现层债务”做四项最高性价比收口，并补齐 server 路由层缺失的回归测试。

### 1. 测试地雷清理 + 统一 sys.path

**问题**：`tests/` 下 4 个 script 式文件（`test_full_regression.py`、`test_keeper_e2e.py`、`test_keeper_summary.py`、`test_http_regression_current.py`）不是可被 pytest 收集的单元测试——前三个的 `test_` 函数带必填位置参数，第四个在隔离运行时因 `from backend.runtime_store import` 触发 `ModuleNotFoundError: character_assets` 而 collection error，只在全量跑时被其他文件的 `sys.path` 插入掩盖，是顺序相关的隐患。

**修复**：
- 4 个脚本 `git mv` 到 `scripts/manual-checks/`（去掉 `test_` 前缀），修正其 `sys.path` 引导以适配新深度，并附 `README` 说明它们是手动 live 脚本。
- 新增仓库根 `conftest.py`，在任何测试收集前把仓库根与 `backend/` 同时放上 `sys.path`，使单文件运行与全量运行的收集行为一致，彻底消除顺序相关的 collection error。
- `pytest.ini` 增加 `testpaths = tests`，bare `pytest` 只收集 `tests/`。

### 2. runtime_store loader 区分“缺失”与“损坏”

**问题**：`runtime_store.py` 约 11 个 loader 用 `try: json.loads(...) except Exception: return {}` 静默吞掉解析失败；尤其 `load_state` 在 `state.json` 损坏时返回 `{}`，与“文件不存在”完全无法区分，会静默走 seed-default 把整个会话状态丢掉。

**修复**：抽出统一 `_load_json(path, default, *, backup_corrupt=True)`——缺失返回 default 的深拷贝；解析失败 `logger.exception` 记录，并把损坏文件 `os.replace` 移到 `<name>.corrupt` 保留后再返回 default。机器生成的 session 数据用 `backup_corrupt=True`，用户手编文件（`config/runtime.json`、`character-data.json`）用 `backup_corrupt=False` 只记录不挪动。所有简单 loader 改用此 helper，消除重复样板。

### 3. _history_cache 与核心 read-modify-write 加锁

**问题**：模块级 `_history_cache` 在 `ThreadingHTTPServer` 下被无锁读写；`append_history`、`append/upsert_event_summary`、`save_meta`、history 分片重建等 read-modify-write 只靠 server 层 per-session 进程内锁，跨 session 并发无保护。

**修复**：参照 `player_profile.PLAYER_PROFILE_LOCK`，新增模块级 `_STORE_LOCK = threading.RLock()`，包住 `_history_cache` 读写与 `load_history / save_history / append_history / append_event_summary / upsert_event_summary / save_meta / ensure_history_shards`。用 RLock 以支持 `append_history -> save_history -> invalidate_history_cache` 的嵌套重入。

### 4. server.py 路由分发表

**问题**：`do_POST`（530 行）、`do_GET`（318 行）是扁平 `if parsed.path == ...` 链，每条路由重复 `session_id 提取 → normalize → scope 校验` 样板，且 token 重置样板在每个 early return 重复约 8 处，易漏。

**修复**：
- `_request_scope(method)` context manager 统一请求壳（解析用户上下文 + 多用户 contextvar，`finally` 必定重置），token 重置从约 8 处收敛到 1 处。
- `_resolve_scoped_session(raw, *, allow_missing)` 收敛约 9 处 session 前导，失败时发对应 400/404/409 并返回 None。
- `do_GET/do_POST/do_DELETE` 改为 `_GET_ROUTES / _POST_ROUTES / _DELETE_ROUTES` 的 path→handler 分发表 + 提取的 `_get_* / _post_* / _delete_*` handler；favicon / character-cover 原先的 fall-through 改为显式 `unknown route` 404（行为不变）。
- 新增 `tests/test_server_routing.py`（server.py 首个单元测试）：钉死三张表的精确路由集合、handler 可调用、共享 handler 身份，以及 `_resolve_scoped_session` 与 health 分发行为。

### 验证

- 全量 `python3 -m pytest -q`：`428 passed, 1 skipped`（较改动前 +9，全部来自新 server 路由测试）。
- server.py 重构通过“字符串字面量多重集 HEAD↔工作树 diff”核对：所有响应字段、错误码、消息字符串计数不变，差异仅为有意去重的 session 前导消息与两处显式 404，证明 50+ handler body 转写忠实。
- `_load_json` 行为单测：缺失→独立 default、损坏→default + `.corrupt` 备份、用户配置损坏→原地保留。

### 2026-05-30 (续): 中期项 —— 补测试与 god-function 拆分

承接上一条的地基收紧，本轮推进 REVIEW 列出的中期项：给未覆盖模块补单测，并把两个 god-function 拆成命名可测单元（行为不变）。

补测试（这些模块之前 0 覆盖）：
- `tests/test_atomic_io.py`（11）：原子写入成功/失败的原子性、损坏不污染原文件、json/text/bytes round-trip、`mode` 权限、父目录创建。
- `tests/test_continuity_resolver.py`（9）：important NPC 续场的证据打分、跳过条件、`relevant_npcs` 6 上限、输入不可变（deepcopy）。
- `tests/test_bootstrap_agents.py`（32）：npc/object/clue 三个 bootstrap agent 的 normalize/merge/启发式提取/物件标签校验/name canonicalize，以及 `ensure_npc_registry` 的 LLM-mock 解析、processed_pairs 门控与坏回复 heuristic fallback。

god-function 拆分（行为保持，由既有测试守护）：
- `state_bridge.normalize_state_dict`（466 行）抽出 `_normalize_object_layer`（~190 行：tracked object 合并/退役入 graveyard/possession/visibility/decay）与 `_normalize_signal_layer`（~28 行：carryover signals → risks/clues），主函数降到 ~280 行；由 `test_state_fragment`（127）+ `test_state_keeper_partial_accept` 等 141 个既有测试守护。
- `handler_message.handle_message`（807 行）抽出纯函数 `_recent_history_pairs` 与 `_apply_pending_npc_bios`，并新增 `tests/test_handler_message_helpers.py`（8）直接覆盖。

已识别但本轮未做（风险边界）：`handle_message` 仍无端到端直测（`test_regenerate_turn` 把它整体 mock 了，`test_opening_memory_transaction` 测的是 `opening.initialize_opening_choice_state` 而非 handler）。其 178 行 `finalize_opening_choice` 闭包与多条 guard 路径的深度拆分应先建 characterization 测试 harness（mock narrator / skeleton+state keeper / storage 驱动各路径），再做提取，避免在零覆盖的中枢代码上引入静默回归。

验证：全量 `python3 -m pytest -q` = `488 passed, 1 skipped`（较上一条 +60，全部为新增测试）。

### 2026-05-30 (续2): handle_message characterization harness + finalize_opening_choice 提取

补上前一条标记为"待办"的部分：先给 `handle_message` 建 characterization 测试 harness，再在其守护下把 178 行 `finalize_opening_choice` 闭包提到模块级。

- `tests/test_handle_message_paths.py`（10）：用 fake 替换 narrator / skeleton+state keeper / storage / context / trackers，驱动**真实** `handle_message` 走完每条路径——runtime 提交、debug 块、幂等命中短路、narrator 失败（NARRATOR_UNAVAILABLE）、partial（NARRATOR_INCOMPLETE）、opening-menu guard、opening-choice、opening-choice narrator 失败不提交、opening-command、opening-guard。断言可观察契约（响应形态、是否提交 history/state/meta、幂等缓存），不测 keeper 内部。这是该函数首个端到端覆盖。
- 在 harness 守护下把 `finalize_opening_choice` 提为模块级 `_finalize_opening_choice(choice, *, session_id, ...)`（10 个显式参数，并注入 `finalize_response` / `append_turn_history` 两个 handler-local 闭包）；`handle_message` 从 807 → 632 行。
- 行为不变核验：harness 18 测全过；"字符串字面量多重集 HEAD↔工作树 diff" 完全一致（纯结构搬移，无逻辑字面量改动）。

仍可继续：handle_message 三条 opening guard 路径（menu-guard / guard / command）的响应构建尾部仍有可合并的样板；现已被 harness 覆盖，后续可安全去重。

验证：全量 `python3 -m pytest -q` = `498 passed, 1 skipped`（+10 为新 harness）。

### 2026-05-30 (续3): handle_message opening guard 路径去重

承接 (续2) 标记为"仍可继续"的项。在 characterization harness 守护下，把三条 no-narrator opening 路径（opening-menu guard / opening-guard / opening-command）共用的提交尾部抽成 `_simple_opening_response(reply, *, usage_model, scene_mode, ...)`——三处只在 reply 文本、usage model 标签、scene/trace mode 上不同，尾部（append history → 组装 response → debug 块 → meta 自增 → 幂等缓存 → trace → finalize）完全一致。`handle_message` → 587 行（本条 −45；当日累计 **807 → 587，−27%**）。

行为不变核验：harness 三条 guard 测试（menu-guard / guard / command）+ 全量套件均过；"字符串字面量多重集 diff" 的差异**全部**是"3 份重复尾部 → 1 份 helper + 调用参数"的预期缩减，无任何语义字面量改动。

验证：全量 `python3 -m pytest -q` = `498 passed, 1 skipped`。

### 2026-05-30 本日小结

当日工作分两批提交在 `foundation-hardening` 分支，测试套件 `419 → 498`（+79），全程无回归：
- 地基收紧 4 项（测试地雷/conftest、loader 区分缺失-损坏、`_STORE_LOCK`、server 路由分发表）。
- 补测试：`atomic_io` / `continuity_resolver` / bootstrap agents（原先 0 覆盖）。
- 拆 god-function：`normalize_state_dict` 466→~280；`handle_message` 807→587（含首个端到端 characterization harness）。
- 两处大重构（server 路由、handle_message）均以"字面量多重集 diff"佐证纯结构搬移。

### 2026-05-30 (续4): session e23032 诊断 + meta.json 幂等缓存瘦身

对长会话 `九幽大陆-20260520-e23032`（227 turn pairs）做数据级体检。keeper/selector 整体健康（最近 40 轮 39 `llm-fill` / 0 fallback / 0 state_error / 40 complete；keeper 抽取结构干净），增长基本有界（`resolved_events[-20]`、`knowledge_records[-80]`、`event_summaries[-80]`）。修复了最高性价比项，其余列为 backlog。

**已修复 —— meta.json 膨胀（每轮重写 3.4MB）：**
- 根因：`processed_client_turn_ids` 幂等缓存存了 50 条**完整 response**（每条含 `state_snapshot` ~64KB），而 `state_snapshot` 本就持久化在 `state.json`，是纯冗余；`save_meta` 每轮把整个 meta 重写一遍。
- 修复：`MAX_IDEMPOTENCY_CACHE` 50→8；`save_meta` 改为按**插入顺序**保留最近 N 条（旧的 lexical-key 排序在 client_turn_id 非时序时会误删最新条，顺手修了这个潜在 bug）；handler 缓存前用 `_slim_cached_response` 剥离 `state_snapshot`，命中时从当前 state 重建（保持 response 形态），并把两处 inline 缓存收敛进 `_cache_processed_turn`。
- 效果（e23032 模拟）：`meta.json` 3400KB → ~125KB（~27x），新会话每轮写入相应减小；幂等语义保持（slim 条仍带 reply/turn_id/usage），旧条（含 snapshot）命中时 verbatim 返回，向后兼容。
- 测试：新增 `test_runtime_store_meta.py`（3，含"插入序 vs lexical"回归）；`test_handle_message_paths.py` 更新 slim 缓存断言 + 命中重建 + legacy 条 verbatim。全量 `502 passed, 1 skipped`。

**待推进 backlog（按性价比，证据见会话数据）：**
1. persona/`role_label` 固化单轮微动作 —— auditor 自报 `persona_micro_action_hooks` warning；e23032 npc_roster 实证（灵貂 role="耳朵朝右前方竖着"、灰布衫="手指弯了弯又松开" 被当成稳定特征 → narrator 重复描写风险）。
2. selector 事件召回与最近窗口重叠 —— turn-227 的 4 条 event_hits 有 3 条（turn 224/225/226）已在 6 轮全窗内，却仍经【命中事件索引】重复注入；应排除窗内 turn。
3. session auditor 自动化 —— 现为手动、`diagnostics/` 停在 5-23（会话已到 turn 227）；可挂到 consolidation turn 定期跑并把 warning 浮到 debug 面板。
4. selector bigram 碎片噪音残留（`刀的`/`物正`/`向三`）—— 2026-05-27 修复压住大头但未根除。
5. `actors` 字典只增不减（e23032：23 个仅 6 active）；可压缩长期归档 actor。

### 2026-05-30 (续5): persona hook 单轮微动作固化修复（backlog #2 → done）

落地 (续4) backlog 第 1 项。keeper 把单轮瞬时姿态（"耳朵朝声源转一下又转回"、"喉结动一下"）当成稳定 persona hook 写入 `actor_persona_hooks`，每轮注入【角色注册表】→ narrator 反复描写同一动作；auditor 早已报 `persona_micro_action_hooks` warning。

- 新增 `name_sanitizer.looks_like_transient_posture(text)`：身体部位 + 瞬时动作标记 ⇒ 判为瞬时姿态（比 auditor 的 prose-tuned `micro_action_score` 覆盖更广，耳朵/尾巴/转/竖 等都纳入）。对 e23032 真实 hook 验证：9/9 姿态命中、7/7 抽象倾向保留。
- **渲染层过滤**（`narrator_input._format_actor_registry`）：语气/行为/决策偏好/受压反应字段与 mannerisms 中的瞬时姿态在入 prompt 前剔除——对**存量 + 新**会话即时生效、不动落盘数据、可逆。
- **写入层过滤**（`state_keeper` mannerisms 合并）：瞬时姿态不再存入 mannerisms，避免占满 `[-6:]` 把真实习惯挤掉。
- e23032 实测：灵貂 6/6、陈掌柜 3/3 姿态 mannerism 被剔除，年轻男人保留"短暂停顿/低声回答"等抽象项；"大石后修士"hook 全抽象、零误删。
- 测试：新增 `test_persona_hook_filter.py`（5）；既有 `test_narrator_setting_lock`（注入 mannerisms）与 `test_memory_transaction_guards`（mannerism 持久化断言）均不受影响。全量 `507 passed, 1 skipped`。

### 2026-05-30 (续6): selector 事件召回排除最近窗口（backlog #3 → done）

落地 (续4) backlog 第 2 项。`event_summary_hits` 的 `recency_bonus` 让【命中事件索引】反复召回最近窗口内的事件——这些事件的完整正文/逐回合提纲本就在 prompt 里，纯属冗余浪费预算。

- `event_summary_hits` / `build_selector_decision` 新增 `recent_window_turns` 参数；落在 `(latest_turn - recent_window_turns, latest_turn]`（最近窗口）内的事件在召回时跳过。`context_builder` 传入 `recent_history_pairs`（默认 12）。默认 `0` = 不排除，向后兼容（既有 selector 测试不变）。
- e23032 turn-227 实测：BEFORE 索引 = `[227,226,225,218]`（全在最近 12 轮窗内、已在 prompt 中）；AFTER = `[214,208,211,210]`（全部窗外，真正的远程召回）——4/4 冗余命中被替换为窗外有效召回。
- 正向副作用：窗外事件 distance ≥ 窗长 → `recency_bonus` 归零，排序回归纯话题相关度，更符合"索引 = 窗外召回"的定位。
- 测试：新增 `test_selector_window_exclusion.py`（4）；既有 `test_selector_recall`（默认 0）不受影响。全量 `511 passed, 1 skipped`。

### 2026-05-30 (续7): session auditor 自动化（backlog #4 → done）

落地 (续4) backlog 第 3 项。`run_session_audit`（纯启发式、无 LLM，已落盘 `diagnostics/audit_*.json`）此前只能手动触发，e23032 的 audit 停在 5-23（会话已到 turn 227）。

- `handle_message` runtime 主链在 **consolidation turn**（`is_consolidation_turn`，默认每 3 轮）自动跑一次 audit：读已提交的 history/state/event_summaries，刷新 `diagnostics/audit_latest.json` + `audit_reports.json`（保留最近 20 份）。
- audit 结果精简版（`severity` / `summary` / `issues` 的 type+severity+message）注入本轮 debug 块 `session_audit`，浮到调试面板；完整证据仍只在 `diagnostics/`。
- 整段 try/except 包裹：audit 失败只 `logger.exception`，**绝不阻断已提交的回合**（专门测试 `test_session_audit_failure_never_blocks_turn` 守护）。
- 无 LLM、读已缓存数据 + 两个小 JSON + 启发式扫描，每 3 轮一次，开销可忽略。
- 测试：`test_handle_message_paths.py` 新增 3 项（consolidation 跑 / 非 consolidation 跳过 / 失败不阻断）。全量 `514 passed, 1 skipped`。

### 2026-05-30 (续8): 锁定 important_npc 提升为 actor —— 解锁 NPC 性格/关系生成（石根 案例）

用户反馈：NPC 应"性格稳定 + 关系随经历成长"，但这部分很弱——石根 出现很多轮，性格、与主角关系（临时队友）一直没生成。

诊断（e23032 实测）：石根 是 `locked` / score 9 / `present_now` 的 important_npc + onstage scene_entity（持"路牌"），却**不在 `actors` 里**。根因：unified 模式 `use_llm=False` 只走启发式 `_fallback_actor_candidates`，而它（以及创建时复用的 `_valid_actor_candidate`）的名字模式闸门会丢弃裸专名（石根：非专名识别/非别称/非描述）——专名 actor 本是留给 LLM 路径，而 unified 把它关了。`personality` 与 `relationship_to_protagonist` 只挂在 actor 上，keeper 的 `persona_patches` / `npc_relationships` 也只绑定既有 actor_id → 没 actor 槽 = 性格/关系全被丢。

修复（用户选"先做解锁"）：`_fallback_actor_candidates` 新增 trusted 路径——把 `locked` 且（`present_now` 或本轮被提及）的 important_npc 作为候选并标 `trusted`；`_valid_actor_candidate` 对 trusted 候选跳过名字模式闸门（保留 junk/protagonist 过滤）。依据：important_npc 的锁定本身已是 importance tracker 验证过的"反复出现人物"信号。初始 identity 用中性 `相关场景人物`，不固化情景化 role_label。

效果：e23032 模拟下一回合即把 石根 建成 `npc_019`（personality 空，待 keeper 填）；该会话 locked+present 的 `['石根','灵貂']` 中仅 石根 新增（灵貂已是 actor），无 actor 洪泛。成为 actor 后，keeper 后续即可往他身上挂性格钩子 + 关系。

第二层核查（turn-trace 实证，40 轮）：keeper 其实**会**产出关系——`npc_relationships` 出现 14/40 次，**含 turn-194 给 石根 的"初识"**；只是绑定要求 NPC 已是 actor（`_find_actor_id_by_name` 找不到就丢），所以石根 的关系被丢弃了。`persona_patches` 仅 5/40 且几乎全是灵貂——因为 keeper prompt 明确"persona_patches 只能绑定已存在 actor_id"，石根 不是 actor 自然不写。**结论**：relationship 与 personality-hooks 都被"非 actor"卡住，本次解锁**同时打通两者**——石根 入册后，keeper 已有的关系产出会绑定、且 keeper 变得有资格给他写 persona_patches。无需额外改动；跑几轮后查 石根 的 `relationship_to_protagonist` 与 `actor_persona_hooks` 即可验证。

测试：新增 `test_actor_promotion.py`（4）；既有 `test_actor_registry` 不受影响。全量 `518 passed, 1 skipped`。
