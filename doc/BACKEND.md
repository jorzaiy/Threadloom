# Threadloom Backend

第一版后端仍采用 Python 标准库实现，目标是先跑通最小链路，不先引入额外框架依赖。

## 当前文件

- `server.py`：HTTP 服务入口
- `handler_message.py`：`POST /api/message` 主链入口
- `runtime_store.py`：session 目录、文件读写（原子写入）与状态快照
- `bootstrap_session.py`：新 session bootstrap
- `context_builder.py`：runtime 上下文装配；当前 narrator 输入是“强约束层 + 连续性层 + 候选知识层”的分层装配，不是只有 `recent window + keeper archive`
- `narrator_input.py`：narrator prompt 拼装；含 `_format_knowledge_scope()` 渲染结构化知情边界、`_format_actor_registry()` 渲染不可变角色注册表
- `model_config.py` / `model_client.py`：模型配置与模型调用（含 429/503 自动重试）
- `local_model_client.py`：本地模型调用（含 429/503 自动重试）
- `card_hints.py`：卡级语义提示加载器，从 `character-data.json["hints"]` 读取实体分类 token、NPC 角色映射、persona 原型等
- `state_bridge.py`：root `memory/state.md` 到 session-local `state.json` 的桥接；负责 state 清洗、稳定合并、object lifecycle、possession/visibility 合法覆盖与 `knowledge_scope` 本轮 delta 标准化
- `state_keeper.py`：优先用统一模型调用链提取结构化 state（数据驱动，不依赖特定角色卡）；fill prompt 当前只维护物品、持有关系、情报与信号，不再维护 NPC 基础设定；fill 输出按增量 patch 处理，不应全量重写 object / knowledge 层
- `state_updater.py`：`state_keeper` 失败时的保守兜底（仅延续上一轮状态 + generic 推理）
- `summary_updater.py`：围绕当前 state + 最近 turn 生成 session-local summary；当前主要作为写回 / 调试产物，不再进入 narrator 主输入
- `summary_chunks.py`：固定 12 轮分段 dense summary；旧 chunk 不重写，供 selector 在 12 轮外检索回流
- `lorebook_distiller.py`：角色卡导入 / 手动重建时把 `lorebook.json` 固化为 `lorebook-foundation.json` 与 `lorebook-index.json`
- `persona_updater.py` / `persona_runtime.py`：session-local persona 流转与展示骨架
- `arbiter_runtime.py` / `arbiter_state.py`：最小 arbiter 主链与状态合并
- `turn_analyzer.py`：用户输入 + scene signal 的统一分析层
- `thread_tracker.py`：active threads 更新；按类型分级保留（`THREAD_RETENTION_CONFIG`），含 `cooling_down` 中间态和 `resolved_events` 归档
- `actor_registry.py`：narrator 回复后的不可变角色注册表；只创建新 actor，已有 actor 的姓名、别称、性格、外貌、身份不再覆盖；同时维护 12 轮未提及归档索引，并把物品 / 情报绑定到 `actor_id`；`knowledge_records` 吸收本轮 `knowledge_scope` 时会做轻量相似去重
- `event_ledger.py`：事件账本；产出阶段事件摘要，不再负责人物短期状态写回
- `important_npc_tracker.py` / `continuity_resolver.py`：重要人物与连续性稳定器
- `opening.py`：opening 菜单与开局状态机
- `card_importer.py` / `import_character_card.py`：角色卡导入与规范化产物生成
- `character_assets.py`：角色卡 source 目录下的导入产物与封面资产读取
- `session_lifecycle.py`：new game / delete / session list
- `regenerate_turn.py`：partial 回复回滚与重试
- `user_manager.py`：多用户管理底层保留模块（bcrypt 密码认证、session token 管理），当前产品面默认关闭
- `object_bootstrap_agent.py`：物品抽取 bootstrap（四策略启发式→LLM判定→merge）
- `clue_bootstrap_agent.py`：情报抽取 bootstrap（模式匹配→LLM分类→merge）
- `npc_bootstrap_agent.py`：NPC抽取 bootstrap（对话启发式→LLM分类→merge）
- `import_sillytavern_chat.py`：SillyTavern JSONL 聊天记录导入（CLI + API）
- `legacy_tools/`：历史迁移 / 实验脚本归档目录，不属于当前主链运行时

## 当前主策略

当前已经不是 stub backend，而是最小可运行主链：
- narrator 已接上真实模型调用
- 新 session 会继承 root `canon / summary / state`
- state / summary / persona / threads / important NPC / actor registry 都已接入 session-local 写回
- narrator 当前默认只吃低干扰上下文：`runtime_rules / preset / slim character_core / player_profile / actor registry / items / knowledge / 最近 12 轮完整窗口 / user input`
- `state` 的 `time/location/main_event/onstage` 不再进入 narrator prompt；当前事实以最近 12 轮为准
- `event` 不再进入 narrator prompt，也不再写回 state；12 轮外历史改由固定 `summary_chunks` 通过 selector 条件召回
- 世界书默认分三层消费：首个 narrator 回合注入原始 alwaysOn/foundation 世界书的大预算片段；后续每轮常驻短 `foundation` 护栏；情境条目由 selector / index 命中后回源到原始 `lorebook.json` 片段注入。世界书不是当前场景事实源
- `state_keeper` 优先，`state_updater` 兜底
- arbiter 已接入主链，不再只是文档占位
- partial reply 有独立处理路径，不再继续污染事实层
- opening 已升级为独立状态机
- session 生命周期已覆盖：新游戏、切换、删除、partial regenerate
- 同一 `session_id` 的写请求现会串行执行，降低并发写冲突
- 会话归档功能已取消：新游戏只创建新 session，不再把旧 session 移动到 `archive-*`；session list 也不再返回 `archived` 字段。历史 `archive-*` 目录仅作为旧数据存在，不进入当前会话列表
- `state_keeper` 已加入低信号拒收与回归检查
- `state_fragment` 已前移到 narrator / state_keeper 主链，并在失败分支提供 `fragment-baseline`
- `state_keeper_candidate` 当前可作为 `skeleton keeper` sidecar 先产出最小骨架，并并入 `state_fragment` 再交给完整 keeper
- skeleton keeper 当前每个完整回复后都会运行，避免非合并轮长期沿用旧 `state_fragment` 造成硬锚点滞后；完整 fill keeper 仍按合并轮运行
- 完整 `state_keeper` 当前已切到 `fill-mode`：先以 `state_fragment + skeleton` 形成基线，再只补物品、情报与信号；默认每 2 轮运行一次，不再接管 `time / location / main_event / onstage_npcs / immediate_goal` 这类当前硬锚点
- actor registry 当前在每个完整 narrator 回复后运行：narrator 后处理只允许创建新 actor，已有 actor 的姓名、别称、性格、外貌、身份视为锁定，不允许后续覆盖；持续承担行动链、关系压力或信息承载功能的匿名个体也可用正文稳定称呼建 actor；LLM 失败时不从旧 `scene_entities` fallback 建 actor，避免把旧污染写成不可变设定
- actor registry 创建新 actor 时会读取最近 1~3 对 turn，因此上一轮 actor registry LLM 失败后，下一轮仍可从 recent window 补建，不需要依赖脏 fallback
- actor registry 已内置 `protagonist`，物品持有和情报记录可统一绑定到 `actor_id`；`possession_state` 会补 `holder_actor_id`，`object_visibility` 会补 `known_to_actor_ids`，本轮 `knowledge_scope` 会派生长期 `knowledge_records`
- 12 轮未被正文提及的 actor 会进入 `actor_context_index.archived_actor_ids`，只影响后续上下文注入，不修改 actor 基础设定；再次被正文提及时会回到 active
- 每满 12 个完整 user/assistant pair 生成一个不可变 dense summary chunk，保存到 `memory/summary_chunks.json`；chunk 覆盖固定区间，不重叠、不滚动覆盖
- opening-choice 分支现在不再“只生成正文然后直接返回”；首轮开局正文会进入 `state_fragment -> skeleton keeper -> fill keeper -> thread/important_npc` 写回链，避免正文与 state 从第一轮开始分叉。当前这条链通常能落下 `time/location/main_event/onstage/immediate_risks/carryover_clues`，但 `immediate_goal` 仍可能偏保守
- `main_event` 与 `active_threads.main.label` 当前已改为条件同步：不再让较慢更新的 `main_event` 无条件覆盖主线程标签；只有当 `main_event` 质量明显更高，或主线程标签仍是占位值时，才允许它接管主线程标签
- `active_threads` 当前已降为“state/debug 辅助层”的实验状态：数据结构仍保留，但不再默认进入 narrator prompt，也不再作为 selector 的主要命中依据；归一化层也不再允许它反向补 `relevant_npcs / scene_entities / main_event`
- `carryover_signals` 统一信号层已接入状态 schema并真实落盘：设计目标是让 keeper 优先维护“后续仍会影响局势的统一信号”，再由兼容层派生旧 `immediate_risks / carryover_clues`；当前真实回合里 keeper 仍常直接产出旧字段，但状态归一化层已会把旧字段反推回统一信号层并持久化
- 普通 `state_updater` 路径当前也会补 `carryover_signals`，不再只在 full fill keeper 回合里存在；`thread_tracker / context_builder / state_snapshot` 等核心消费点已开始优先使用统一信号层，再兼容旧字段
- `onstage_npcs` 当前只作为 state/UI 快照存在，不进入 narrator 主 prompt，也不承载长期人物基础设定；长期人物基础设定进入不可变 `actors`
- narrator prompt 当前不靠列举“翻墙/离场”等剧情关键词维持连续性，而是通过完整 recent 12 和通用原则约束空间关系、视线范围、人物控制权与行动链的承接
- 当前目标分工草案：
- `event`：中程检索层，服务于 recall / summary，不默认主导 narrator
- `signal`：当前方向约束层，可直接进入 narrator / selector
- `summary`：长程压缩层，只在 recent window 不足时条件回流
- `thread`：state/debug 辅助层，当前实验中已去主导化
- `actor registry`：长期人物基础设定层，只创建新 actor，不维护短期状态

当前 `event` 链的实现边界：
- event 当前已改为真正读取最近 `1~3` 对 `user/assistant` 窗口，而不是只摘要当前轮 narrator prose
- `prev_state` 当前已在调用侧修正为“本轮前状态”，避免 event 用当前态伪装上一轮状态
- event 当前不再输出或合并 `status_transitions`；短期状态只保留在最近窗口 / 当前硬锚点，不写入长期 actor 基础设定
- heuristic fallback 当前也按多回合窗口工作，不再优先挑天气/氛围句；当前仍可能不如 LLM 版本稳定，但 summary 已开始更像阶段事件压缩器
- `state_updater` 已更偏保守继承，不轻易覆盖已有高信号状态
- narrator 对“半句中止但 provider 未标 partial”的返回增加了不完整输出保护，避免坏回复继续污染事实层
- state fallback 现在会更严格地区分“可持续追踪物件”和“短语残片 / 动作词片段”
- 已支持对旧污染 session 做离线重建，直接修复 `state / threads / important_npcs / summary`
- state snapshot 已可直接提供前端实体展示结构
- web 配置项中的 `default_debug / show_debug_panel / history_page_size` 已可驱动 API 与前端
- 前端默认会话选择已改为最近更新会话优先
- 角色卡信息当前会动态读取角色卡元数据和缩略封面图；角色卡切换与导入入口现已主要收进设置面板
- narrator prompt 已加入更通用的知情边界约束，减少 NPC 间私下信息自动外溢
- NPC 间信息隔离已升级为结构化知识系统：keeper 每轮只提取本轮新增 `knowledge_scope` delta，`state_bridge.py` 只保留本轮 delta 不再长期合并，`actor_registry.py` 派生 actor-id 版长期 `knowledge_records` 并做轻量相似去重，`narrator_input.py` 渲染为结构化知情边界
- 所有文件写入已改为原子写入模式（`_atomic_write_text()` / `_atomic_write_json()`）：写临时文件 → fsync → `os.replace`（POSIX 原子），防止崩溃/断电导致数据损坏
- 模型调用已加入 API 韧性层：`_retry_on_rate_limit` 装饰器在 429/503 错误时自动指数退避重试（最多 3 次），尊重 `Retry-After` 响应头；远端和本地模型调用均已覆盖
- `summary` 与独立 `mid digest` 当前不再作为 narrator prompt 的主输入块
- 世界书注入当前已改成“开局原文定底 + 导入期蒸馏护栏 + 运行期 selector 回源”：避免普通回合每轮塞整段 raw lore，同时避免只给蒸馏摘要导致 narrator 误以为世界书只有摘要内容
- 导入器会在写出 `lorebook.json` 后生成两个缓存文件：
  - `lorebook-foundation.json`：每轮常驻的短世界基础 / 身份边界 / 规则口径
- `lorebook-index.json`：条件召回的情境 lore 索引，条目保留 `source_entry_ids`；其中 `keywords` 只作为检索索引，不作为剧情触发规则。运行期命中 index 后优先按 `source_entry_ids` 回到 `lorebook.json` 取原文片段，而不是直接把蒸馏摘要当完整知识交给 narrator
- `lorebook_distiller.py` 默认尝试用 `state_keeper_candidate` LLM 蒸馏；当前用户配置建议使用 `deepseek-v4-flash` 这类稳定付费模型。蒸馏调用会覆盖普通 keeper 的输出预算（独立 `max_output_tokens`），遇到空回复或 JSON 解析失败会自动重试；仍失败时使用 heuristic fallback，并在产物 `provider` 字段标记
- narrator prompt 中对应块为 `【世界书基础规则】` 和 `【情境世界书】`；`【世界书基础规则】` 明确标注为“不完整常驻护栏”，`【情境世界书】` 标注为 selector 命中后的相关世界书内容。旧 raw `【世界书】` 块不再作为普通回合默认入口
- 情境世界书默认先用 index 小预算定位（当前默认 2 条 / 约 700 字），再回源注入原始条目片段（默认约 1800 字），避免普通观察轮因 recent window 中出现世界名词而召回过多 lore，同时保留原文约束与局部结构
- turn trace / debug 当前会自动记录：
  - 实际注入的 lorebook 条目列表
  - 蒸馏 foundation 与 index 命中来源
  - index 命中后的原始世界书回源片段 `source_hits`
  - `【世界书基础规则】` / `【情境世界书】` 总字符数
  - prompt 各大区块字符占比

## 当前配置边界

当前配置层已经分成两类：

- 共享配置：
  - `config/runtime.json`
  - 用于内容层来源、全局运行策略、默认模型参数

- 用户配置：
  - `runtime-data/<user>/config/site.json`
  - `runtime-data/<user>/config/model-runtime.json`
  - 用于当前用户自己的站点、模型选择

当前明确结论：
- 单用户当前可用，默认用户目录是主工作路径
- 单站点是当前产品层简化，不是永久平台承诺
- `Narrator / State Keeper` 已有用户级模型选择
- `Analyzer / Arbiter / Skeleton Keeper / Lorebook Distiller` 这类高级角色当前不暴露给普通用户界面，但已可通过用户级 `model-runtime.json -> advanced_models` 做高级覆盖
- 当前角色卡管理也已进入 Web UI：
  - 当前用户角色卡列表可枚举
  - 可切换当前活跃角色卡
  - 可在设置面板内导入新的角色卡
  - 当前默认用户标签固定显示为 `default_user`
  - 当前阶段不做用户管理，产品面默认仍为单用户 `default-user`
  - 多用户相关底层代码已保留在 `user_manager.py`，但 `/api/users`、`/api/multi-user`、`/api/auth/login`、`/api/auth/logout` 当前统一视为实验态关闭
  - `state_keeper_candidate` 当前建议绑定稳定模型；本地默认用户已切到 `deepseek-v4-flash`，避免世界书蒸馏阶段出现空回复 / 截断
  - 三条 bootstrap（NPC/物品/情报）均已通过 LLM 回合测试

当前建议配模方向：
- narrator 继续使用强远端模型
- `state_keeper` 与 `state_keeper_candidate` 当前建议使用稳定低温模型；默认用户当前使用 `deepseek-v4-flash`
- skeleton keeper 和 fill keeper 均使用同一模型，通过 prompt 分工
- 当前 keeper 主链路是：
  - `skeleton keeper`（`deepseek-v4-flash`）→ 最小骨架
  - `fill keeper`（`deepseek-v4-flash`）→ 补物品、情报与信号
  - `heuristic fallback` → 最终兜底
- `fill keeper` 当前按增量 patch 思路运行：已有 NPC / 物件默认沿用，只在明确新增或明确变化时输出，避免低质量后抽取覆盖高质量旧状态
- NPC 与物件绑定当前由 `possession_state` 驱动：标准化层会把 holder 对齐到稳定 NPC 主名，并自动写回 `tracked_objects[].owner / bound_entity_id` 与 `scene_entities[].owned_objects`；新 holder 必须来自当前人物、scene entity、actor registry 或 protagonist aliases，非法 holder 不覆盖旧合法归属
- object 层支持 `lifecycle_status: active | consumed | destroyed | lost | archived`；非 active 物件会从 active `tracked_objects / possession_state / object_visibility` 退出，并写入 `graveyard_objects` 防止后续幻觉复活
- turn_analyzer 可在 narrator 不变前提下评估是否跟着切本地

当前 keeper 调教样本分工：

- `维克托·奥古斯特`
  - 用于校准结构清晰场景下的：
    - `main_event`
    - `threads`
    - `objects`

- `九幽大陆`
  - 用于校准无系统级 NPC 前提下的：
    - 动态 NPC 抽取
    - 长文探险线物件/线程稳定性
    - keeper archive 延续性
  - 当前已经证明：
    - `gemma-4-31b-it` 可以在中等窗口长跑中稳定保住人物、主事件、线程
    - 弱语义 `role_label` 已开始生效，不再长期全部停在 `待确认`

- `血蚀纪`
  - 用于校准：
    - 日常互动型文本的场景锚点
    - 事件标签
    - 假人物过滤

## 角色卡导入 v0.3

当前推荐的角色卡导入产物已经改成分层结构，而不是把 Tavern 原字段直接散落到运行时文件：

- `character-data.json`
  - 角色核心、简介、来源信息、精简系统摘要
  - 从 v0.4.2 起完整保留以下 v2/v3 字段：`nickname`、`mes_example`、
    `post_history_instructions`、`tags`、`character_version`、
    `talkativeness`、`creator_notes_multilingual`、`extensions`
  - `source` 子字段记录 `creator`、`creation_date`、`modification_date`
  - 长字段使用边界感知截断（`_truncate_at_boundary`）：
    `personality` 1500 / summary 2400 / system_prompt 4000 / creator_notes 2000
- `lorebook.json`
  - 规范化世界书条目，导入器为每条补 `entryType / runtimeScope / featured`
  - 区分：foundation（底板规则/世界观）、situational（场景相关）、
    NPC / cast / faction 可调入层
  - 从 v0.4.2 起完整保留 SillyTavern 字段：`selective`、`selectiveLogic`、
    `position`、`depth`、`probability`、`useProbability`、
    `caseSensitive`、`matchWholeWords`、`group`、`groupOverride`、
    `groupWeight`、`vectorized`、`disable`、`extensions`、`secondary_keywords`
  - lorebook 顶层保留 `description`、`scan_depth`、`token_budget`、
    `recursive_scanning`、`extensions`
  - 仅触发用的 keyword-only 条目（content 为空但 keywords 非空）也会保留
  - 历史上曾提供过 metadata 回填脚本；这类一次性迁移工具现已归档到 `backend/legacy_tools/`
- `openings.json`
  - 开局模式、开局 bootstrap、开局选项
  - `mode: direct` 表示单一开局，运行时直接展示 `menu_intro`，不追加“可用开局 / 随机开局 / 报数字”菜单提示
  - `mode: menu` 表示确实存在多个开局候选，运行时才消费 `options` 并进入 opening choice 分支
  - 单 `first_mes` 角色卡会导入为 `direct`，不会再被误当作多开局；`alternate_greetings` / `group_only_greetings` 等多个候选才会保留为 `options`
  - 每个 option 带 `kind`：`first_mes` / `alternate_greeting` / `group_only_greeting`（v3）
  - 导入期会对开局文本做基础 SillyTavern 占位符替换：`{{char}}` → 角色名，`{{user}}` → `玩家`；运行时展示旧导入文件前也会兜底替换一次
- `system-npcs.json`
  - 从导入卡中明确提取出的系统级 NPC
  - 当前分成：
    - `core`：最明确、最值得直接进入运行时的人物
    - `faction_named`：势力条目中的命名人物
    - `roster`：更边缘的命名人物
    - `items`：上述三个桶的合并（**包含 roster**，从 v0.4.2 起修复，
      之前 roster 被静默丢弃）
  - 英文/拉丁文角色卡的内嵌 NPC 由 `_extract_embedded_npcs_latin` 兜底识别
- `import-manifest.json`
  - 导入来源、产物路径、统计信息
- `assets/`
  - 封面图与缩略图
- `imported/`
  - raw card 与原始 PNG 备份

当前导入命令：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.png
```

或：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.raw-card.json
```

当前运行时的消费方式：

- `opening.py` 优先读取 `openings.json`
- `context_builder.extract_system_npc_candidates` 按 `core → faction_named → roster`
  分级 fallback，直到达到 limit；每个候选带 `source` 字段（`system_npc` /
  `system_npc_faction` / `system_npc_roster`）
- `state_bridge.infer_role_label` 通过 `system-npcs.items` 查 role label
  （`items` 现在包含全部三个桶）
- `persona_updater._infer_candidate_identity` 接受任何 `system_npc*` 来源
- `runtime_store.py` / `server.py` 优先读取 `assets/` 下的角色卡封面
- 导入器当前会额外过滤 SillyTavern 前端模板、隐藏脚本、状态栏、人际模板等 runtime 噪声，避免它们进入最终 `lorebook.json`

当前目标不是“导得越多越好”，而是：

- 只保留对 runtime 真正有价值的结构产物
- 把“世界知识”“开局菜单”“系统级 NPC”“封面资产”明确拆开
- 减少旧 Tavern 前端字段、视觉字段、规则缝合内容直接污染运行时

## API Key 安全

`model_config.py` 支持环境变量引用：在 `providers.json` 的 `apiKey` 字段中使用 `$ENV_VAR_NAME` 或 `env:ENV_VAR_NAME` 格式即可从环境变量读取密钥。

## 当前仍不稳定的部分

- `state_keeper` 仍主要从 narrator prose 反提物品、情报与信号，actor registry 也仍是 narrator 回复后的后处理调用，而不是同一次 narrator 输出中的原生 sidecar
- keeper/event/signal/thread/summary 数据边界仍偏重叠，尤其是“事件事实”“当前方向信号”和“长期情报记录”的关系需要继续整理
- actor registry 当前只保证基础设定不可覆盖；新 actor 创建质量仍依赖模型抽取，误建一次性 NPC 的风险仍存在，但 LLM 失败时不会从旧 `scene_entities` 自动补建
- arbiter 仍主要覆盖少数高风险事件类型
- analyzer / state keeper 虽已分模，但默认配置仍偏实验态
- ~~主角 runtime 仍未独立落地~~ → 已在 `actors.protagonist` 中作为特殊 actor 落地
- ~~NPC 间信息隔离仍未独立成结构化 knowledge scope 层~~ → 已补 `knowledge_scope`
- ~~已解决事件归档层仍未独立落地~~ → 已补 `resolved_events`

## 近期变更

### State Keeper 三层架构与调度策略

**修改前**：`handler_message.py` 每轮无条件调用 `call_state_keeper()`（fill LLM），对所有字段做全量提取。这导致：
- 每轮都消耗 LLM 配额（~5KB 输入 / 480 tokens 输出）
- keeper 只能看到最近几轮上下文，无法提取跨轮的长期目标
- 主要事件和 `immediate_goal` 精度偏低

**修改后（三层混合策略）**：

| 层                | 模块                | 触发频率           | 输入大小 | 提取字段                              |
| ----              | ----                | ----               | ----     | ----                                  |
| 启发式            | `state_updater.py`  | 每轮               | ~1KB     | 全字段（保守推理）                     |
| Skeleton LLM      | `state_keeper.py`   | 每完整轮           | ~2KB     | time, location, main_event, onstage_npcs, immediate_goal |
| Fill LLM          | `state_keeper.py`   | 每 N 轮（默认 3）  | ~5KB     | carryover_signals, tracked_objects, knowledge_scope |
| Actor Registry    | `actor_registry.py` | 每完整轮           | ~2KB     | actors, actor_context_index, actor-id bindings |

- 读取 `config/runtime.json` 中 `memory.consolidate_every_turns`（默认 3）
- 非合并轮使用 skeleton + `build_state_from_fragment()` + `update_state()` 轻量更新
- opening-choice 首轮当前是特殊链路：会先跑 skeleton + fill keeper，再接 thread/important_npc 写回，不直接复用普通非合并轮的 `update_state()` 路径
- 诊断信息中 `provider` 标注为 `skeleton+fragment` 或 `full_fill`
- 当前字段稳定性大致排序：`time / location / main_event` 高于 `onstage_npcs / immediate_risks / carryover_clues`，而 `immediate_goal` 仍偏保守。

### 上下文窗口与输出优化

**修改前**：
- `recent_history_turns`: 12 轮
- `narrator.max_output_tokens`: 1200
- `lorebookStrategy.maxTotalChars`: 2200（world-sim-balanced 预设）

**修改后**：
- `recent_history_turns`: **8 轮**（`config/runtime.json`）— 减少约 30% 上下文注入量
- `narrator.max_output_tokens`: **1000** — 降低每轮生成的 token 消耗
- `lorebookStrategy.maxTotalChars`: **1500**（`character/presets/world-sim-balanced.json`）— 减少世界书注入上限

单轮总上下文约从 30KB 降至 22-25KB。

### 角色卡导入管线精度优化

提升 3 个 bootstrap agent 的提取精度上限：

| 参数                                     | 修改前  | 修改后  | 文件                         |
| ----                                     | ----    | ----    | ----                         |
| NPC 注册表发送给 LLM 的数量              | 10 条   | 20 条   | `npc_bootstrap_agent.py`     |
| NPC 别名保留数量                          | 8 个    | 12 个   | `npc_bootstrap_agent.py`     |
| NPC notes 截断长度                        | 80 字符 | 200 字符| `npc_bootstrap_agent.py`     |
| 物件候选发送数量                          | 15 个   | 25 个   | `object_bootstrap_agent.py`  |
| 物件标签最大长度                          | 6 字符  | 8 字符  | `object_bootstrap_agent.py`  |
| 线索候选发送数量                          | 8 个    | 12 个   | `clue_bootstrap_agent.py`    |

另在 `card_importer.py` 中新增 `_truncate()` 辅助函数，当字段被截断时自动输出 WARNING 日志，便于排查导入精度问题。

### 角色卡导入审查与修复（v0.4.2）

详见 `doc/audit/CARD-IMPORT-AUDIT.md`。本次修复主要解决三类问题：

1. **数据丢失**：`system_npcs.items` 漏放 `roster`、SillyTavern v2/v3 大量字段未读、
   `personality` 截到 240 字符。
2. **误伤**：`'小美'`/`'血蚀纪'` 等具体作品人名被写死成黑名单、faction 推断硬编码、
   主角名长度限制把英文名全拒绝。
3. **覆盖面**：`_extract_embedded_npcs` 只识别中文条目，英文卡的内嵌 NPC 兜底由新加的
   `_extract_embedded_npcs_latin` 处理。

修复点对应单测 `tests/test_card_importer.py`（21 个）+ 端到端测试
`tests/test_card_importer_e2e.py`（3 个）。

### 前端 UI 重构

- **设置面板** 重组为三页签：连接与模型 / 角色卡 / 用户设定；未激活页签使用绿色背景
- **侧边栏合并至浮动面板**：原 `stateColumn` 侧边栏的 4 个分区（当前状态、NPC、物件与线程、NPC 详情）已移入调试浮动面板，并新增"调试诊断"折叠区；移除了侧边栏按钮
- **Session Dock 简化**：会话归档功能已取消，Dock 只显示当前可用会话；开始新游戏不再移动旧 session，也不再展示归档分隔线
- **角色卡缩略图缓存**：移除了 `?t=${Date.now()}` cache-buster，启用浏览器缓存和 `loading="lazy"`
- **角色卡切换**：添加了 error handling 和自动关闭设置面板

### 角色卡导入修复（v0.4.3）

- **嵌套 JSON 世界书展开**：部分 Tavern 卡会把真正的世界书写在外层条目的
  `content` JSON-like blob 的 `entries[]` 里，且字符串内含未转义换行。导入器现在会宽松解析这类结构，展开为正常 `lorebook.json` 条目，并标注 `source_kind: embedded_lorebook_json`。
- **嵌套条目分类**：内层 `时间线 / 阵营 / location / Dynamic Rules / 动态规则 / 异能 / 晶核` 会按标题精确分类为 `history / faction / region / rule`，避免被外层标题或正文关键词误导。
- **runtime 噪声过滤**：`enabled: false` 或 `disable: true` 的世界书条目不再进入 runtime `lorebook.json`；`初始引导` 等玩家设定提示也会从 runtime 世界书中过滤。
- **显式 NPC 保留**：`npc：...` / `Npc-...` 这类显式 NPC 条目即使正文包含 `{{user}}`，也不会被误判为模板并跳过。
- **管理卡片短简介**：导入器会生成 `displaySummary`，角色卡管理优先展示这份清洗后的短简介，避免把作者指令、人际模板、状态栏、YAML 人物细节直接显示在卡片下方。
- **测试覆盖**：`tests/test_card_importer.py` 已补充嵌套世界书、disabled 条目过滤、显式 NPC 模板占位符、管理卡片短简介等回归测试；当前导入器相关测试为 `36 passed`。

### 前端交互修复（v0.4.3）

- 顶部 header 改为左上角浮动胶囊，只保留 logo / `Threadloom` / 当前用户与角色卡，窄屏与移动端隐藏，减少对正文区域的占用。
- 设置面板重组为 `当前世界 / 导入资产 / 玩家设定 / 模型连接`：当前世界内直接列出角色卡管理、Session 管理和聊天记录导入；导入资产只处理角色卡导入。
- 胶囊内 `Threadloom` 打开模型连接；当前用户/世界区域打开当前世界页签。窄屏与移动端隐藏胶囊。
- Session 管理弹层已移出 composer 表单，新增关闭按钮，并修复点击快捷入口后被全局点击监听立刻关闭的问题；当前世界页签也内嵌会话列表，可直接切换、删除或新建会话。

### 世界书蒸馏回归（v0.4.4）

- `state_keeper / state_keeper_candidate` 默认用户配置已切到 `deepseek-v4-flash`，用于提高 keeper 与世界书蒸馏稳定性。
- 四张当前角色卡均已重建 `lorebook-foundation.json` / `lorebook-index.json`，产物 `provider: llm`。
- HTTP 3 轮回归从 `开始游戏` 开局验证通过：开局与后续 3 个正文回合均正常返回。
- narrator prompt 注入审查结论：每轮均注入 `【世界书基础规则】`，普通正文轮情境世界书限制在约 2 条 / 700 字；旧 raw `【世界书】` 块不再出现。
- turn trace 已补充 opening-choice 分支的 `prompt_block_stats` 与 `lorebook_injection`，便于直接审查每轮注入结构。
