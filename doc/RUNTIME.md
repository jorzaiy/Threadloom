# Runtime Flow

**当前版本：v1.0**

## 一轮消息的最小流程

## 分层刷新策略

### 每轮轻刷新

每轮都读取：
- `runtime-rules`
- active preset
- 当前角色卡核心与世界约束字段
- 统一 JSON 玩家档案渲染出的短 `【玩家档案】`；自然语言源文本只用于设置页整理和审计，不直接进入 narrator。详细 profile 数组会拆成可检索 section，本轮若强锚点命中身世、外貌、能力、心理、私密边界等主题，selector 可额外注入 `【命中玩家档案细节】`。
- `state`
- `scene persona seeds`
- 最近窗口：默认读取 `12` 对 complete history，其中靠近当前的 `6` 对以完整正文进入 narrator，前段回合以逐回合 event outline 承接

这些不是同一优先级：`runtime-rules`、当前角色卡世界观、时代、题材、身份边界和世界机制是最高约束；recent history 与本轮用户输入只负责短期场景承接，不能反向改写角色卡世界。用户主角只是世界内角色，可以尝试行动和表达态度，但不能直接指定 NPC 服从、行动必然成功、关系成立、物品凭空出现或客观结论生效。

### 中等刷新（固定摘要窗口默认每 12 轮）

建议周期性重读：
- `relevant NPC profiles`
- `longterm persona seeds`
- 当前 relevant lore
- keeper archive

目的：
- 防止场景慢漂移
- 防止 relevant NPC / lore 选择长期失焦
- 用较早结构记录补足窗口外连续性

当前实现补充说明：selector 选中 NPC profile target 后，优先读取角色卡 source 下的 markdown profile；若缺失，会回落到当前 session 的 `persona/scene`、`persona/longterm`、`persona/archive` JSON seed，并把其中的身份、persona hooks 与近期观察片段格式化为 narrator 的 NPC profile。这样可以避免“persona 已经生成但 narrator 仍显示 profile missing”的断链。统一记忆事务模式下，旧 persona seed 不再作为 `【NPC 表现层人格】` 自动注入；当前回合表达层一致性优先来自 `state.actor_persona_hooks`，并在角色注册表中按 actor_id 注入。

Selector 对 12 轮外固定 summary chunk 的回流采用“当前 turn 强锚点优先”原则。人物名、地点、物件、事件短语和关系线可作为有效锚点；泛化虚词、短动作残片、称呼碎片和旧情报账本的弱 overlap 只能辅助排序，不能单独触发远期摘要注入。召回规则必须保持角色卡无关，不通过写死具体人名、session id 或剧情专属关键词来强化某个个案。

事件索引召回默认仍偏最近窗口，但当本轮用户或当前事件明确触发“来历 / 背景 / 过去 / 为什么 / 原因 / 听说”等背景追问时，selector 会额外执行长程 event recall：用当前 onstage / relevant NPC、用户显式主题、地点/物件锚点和场景限定服务称呼（如“药铺老板”⇄“药铺掌柜”）扫描更早的 `event_summaries`。长程命中只作为候选补充并继续经过 stale / mundane / sensitive guards，目标是在询问 NPC 来历、旧事件原因或物件来源时，把较早的 first-contact / origin 事件带回 narrator prompt，避免模型因只看到近几轮而自行编造相遇地点或原因。

Session-local persona seed 仍不是完整人物传记。legacy 非统一模式下，它每轮可更新重要度、前后台层级和近期观察，但 observation 只从 assistant 叙事中抽取与该 NPC 相关的短片段，不把用户 prompt 原文写入人物详情，也不把同一片段重复塞进多个字段。统一记忆事务模式下，在线人格写回改为 `state_keeper.persona_patches`：同一次 keeper LLM 只为既有非主角 `actor_id` 写表达层钩子（语气、行为模式、决策偏好、习惯动作、受压反应），经 actor_id/display_name 校验和 prompt-injection 清洗后落到 `state.actor_persona_hooks`。NPC 的外貌印象、语气、习惯动作和性格表现仍必须先在 narrator 正文中可观察出现；narrator 可以自然写出表现层细节，但不能直接输出结构化人物卡或决定是否持久建档。

### 深刷新（设计目标，当前未实现独立 20 轮调度器）

设计上可在以下情况做一次更完整的上下文重组；当前代码没有单独的“每 20 轮 deep refresh/cache rebuild scheduler”，实际依赖每轮重新 `build_runtime_context()`、selector 当前锚点重筛、summary chunk / keeper archive 派生层和 regenerate/repair 触发的派生缓存重建：
- 场景主功能明显切换
- `Onstage NPCs` 明显换了一批
- 当前主事件改变
- 用户明确指出系统理解偏了

深刷新时可重新筛选：
- 当前 relevant NPC 档案
- 当前 relevant lore
- `scene/archive/longterm` persona 的前后台分布

### 手动 Session 审计（MVP）

调试面板提供手动 `Session 审计` 入口，对当前 session 做只读诊断。审计结果写入 session-local `diagnostics/audit_latest.json` 与 `diagnostics/audit_reports.json`，不会进入 narrator prompt、state keeper、selector、summary、persona 或 event summary 主记忆层。

当前 MVP 聚焦叙事风格漂移与污染源隔离信号：

- 最近若干轮 narrator 输出的平均长度、身体微动作词密度与动作拆解模式。
- `event_summaries` 中疑似把 narrator prose fragment 当结构化事件摘要保存的条目。
- `state.actor_persona_hooks` 中疑似固化单轮微动作的表达层钩子。

审计输出只包含 `severity`、指标、证据和建议动作；`safe_auto_repairs` 目前为空，不会自动改写主记忆。若后续需要自动修复，必须先转换为 typed repair（例如替换特定 event summary 或清理特定 alias），并继续禁止把审计解释文本写回 runtime 事实层。

### Step 0. 读取 runtime rules

首先读取：
- `prompts/runtime-rules.md`

这是 runtime 的长期底板。

规则：
- 必须先于 `canon/state/persona` 与最近窗口进入上下文
- 不能依赖当前聊天 session 惯性补全
- 不应被在线会话中的临时 steering 或历史承接覆盖
- 明确角色卡世界设定优先于本轮用户输入和最近窗口；如果用户输入或旧历史要求切换题材、时代、身份边界或世界机制，narrator 只能在当前角色卡世界内转译，不得把冲突前提写成主世界事实
- 明确用户不是作者、导演、GM 或世界主宰。narrator 必须让 NPC、环境、制度、风险、资源、时间与因果自行回应用户主角，避免讨好式让步。

### Step 0.5. 读取 active preset

当前默认 preset id 是 `world-sim-core`。运行时通过 `config/runtime.json` 的 `sources.preset_dir=character/presets` 和用户级 `runtime-data/<user>/presets` 分层解析；默认用户当前对应 `runtime-data/default-user/presets/world-sim-core.json`。不要把旧的 `character/presets` 示例目录当成唯一来源。

Preset 只负责叙事表现，不负责改写事实层、状态写回或系统硬边界。它当前强调：

- 镜头朝外：主角输入只做轻承接，正文主体写外部局势、NPC 反应、环境变化和可感知后果。
- NPC 自主性：NPC 不是主角输入的响应机器；他们应从自身目标、利益、恐惧、关系记忆和信息边界出发行动，可以拒绝、误解、试探、隐瞒、拖延、转移话题或优先处理自己的事务。
- 单轴推进：每轮只推进一个核心轴，避免同时塞入多个新人物、新冲突或新线索。
- 节奏口味：低压场景保留环境暗流、微反应或时间流逝；高压之后优先处理余波、伤势、观察、补给和关系变化。
- 文本卫生：避免 AI 腔和模板词，用具体动作、对白、环境变化和可观察后果替代空泛修饰、升华金句和机械时间。
- 收尾方式：停在客观可接续的新变化上，不做总结、升华、菜单、状态面板或感叹式收束。

当前 preset 的 AI 腔过滤重点包括：

- 空泛垫词：`一丝`、`一抹`、`一种`、`某种`、`那种`、`那层`、`这般`、`如此`、`极其`、`由于`、`莫名的`、`不易察觉`、`像是`、`仿佛`、`似乎`、`好像`、`如同`、`宛如`。
- 高频模板词和动作：`勾勒`、`弧度`、`饱满的弧度`、`嘴角的弧度`、`指节泛白`、`眼睛弯成月牙`、`喉结滚动`、`喉咙滚了一下`、`如蒙大赦`、`不容置疑`、`不容置喙`、`不可置信`、`逼仄`、`浮木`、`铁锈味`、`猪肝色`。
- 套路句式：`不是……而是……`、`没有……反而……`、`是那种……的……`、`那一刻他明白了`、`一眼万年`、`时间仿佛凝固`、`几秒过去了`、括号补丁和破折号解释。

这些是写作口味约束，不是硬编码敏感词系统。模型应优先理解其目标：减少模板化表达，保留场景里的真实行动、阻力、代价和关系变化。

### Step 1. 读取事实源

读取：
- `runtime-rules`
- `canon`
- `state`
- 相关 `npc profiles`
- `persona seeds`
- 最近 rolling window：完整近端正文 + 前段逐回合提纲
- 命中的 keeper archive
- 可调入世界书人物

输出：
- `RuntimeContext`

建议实现时结合 `refresh_policy`：
- 每轮轻刷新读取最低事实层
- 中刷新补充 keeper archive / relevant 层
- 深刷新重建整个 runtime context cache

### Step 2. 构建 scene facts

得到最小结构：

```json
{
  "time": "...",
  "location": "...",
  "main_event": "...",
  "onstage_npcs": ["..."],
  "relevant_npcs": ["..."],
  "immediate_goal": "...",
  "immediate_risks": ["..."],
  "carryover_clues": ["..."]
}
```

输出：
- `SceneFacts`

### Step 3. 解析用户输入

分类为：
- 小动作
- 对话
- 移动 / 转场
- 观察
- 主动介入
- 休整 / 安顿
- 高风险行为

输出：
- `UserTurnAnalysis`
- 是否需要裁定

### Step 4. 必要时裁定

仅在高风险事件需要时调用 arbiter。

输出：
- `ArbiterResult[]`

### Step 5. 构建 narrator 输入

输入源包括：
- 当前 scene facts
- 当前角色卡核心与 `世界设定锁`
- 主角档案：由固定统一 JSON schema 渲染，包含身份、外貌锚点、稳定能力、性格、偏好、背景、心理/剧情、世界适配和私密边界；公开伪装和可见外貌可被场内 NPC 判断，真实性别、隐藏身份或伪装底细只有对应 NPC 已知情时才可用于其称呼与对白
- 当前 onstage / relevant NPC
- persona hooks
- selector 命中的 NPC profile；当 source profile 缺失时，可由 session persona seed 兜底生成轻量 profile
- session persona 中的表现层人格钩子，包括近期观察到的外貌、语气、习惯动作和性格表现
- relevant lore
- available cast / 可调入世界书人物
- 最近完整正文窗口（默认 6 对 user/assistant）
- 同一 recent window 前段逐回合提纲（来自 `event_summaries`，只用于连续性桥接，不要求逐条复述）
- 最近事件时间轴（来自 `event_summaries[].time_anchor/location_anchor`），用于约束旧事件的发生日期/时段，避免 narrator 把前天、昨天、今早、刚才等相对时间混写
- correction rules
- 当前用户输入

`世界设定锁` 是 narrator prompt 的强约束块。它要求候选世界书、召回历史与用户输入先做整体语境兼容性判断；防污染不使用固定关键词黑名单，而是比较因果规则、时代感、社会制度、技术/超自然边界、人物身份与当前角色卡世界是否兼容。

同一个强约束块也负责用户控制权边界：用户输入不是世界命令，只是角色行动尝试。narrator 需要根据角色卡世界给出合理阻力、质疑、失败、延迟、代价、旁人反应或客观限制，而不是让用户一句话获得本应需要过程、证据、资源或权力才能得到的结果。

输出：
- `NarratorInput`

### Step 6. 调模型

生成 RP 正文。

Narrator 回复在写入 history 前会经过确定性质量门禁。除空回复、`finish_reason=length/error` 和明显半截句外，门禁还会拦截模板化叙事退化，例如反复出现 `X的方式是`、`X的方向是`、`不抖的方式是` 等把普通动作拆成解释模板的句式。若命中退化门禁，本轮不会落盘；retry 会在 system prompt 追加纠偏块，明确列出被拒绝片段并要求改写为自然叙事，减少嘴/舌/喉结/眼珠/手指/方向/方式等微动作堆叠，优先推进对白、事实、选择和行动结果。连续重试仍失败时，按 narrator unavailable 处理，不把坏输出写入最近窗口。

输出：
- `reply`
- `model usage`

### Step 7. 写回

更新：
- `history`
- `state`
- `summary`
- `persona seeds`
- scene/archive/restore 流转

写回管线的 LLM 调用策略：

- **统一记忆事务（默认）**：`memory.unified_transaction_enabled` 缺省为开启。每个完整 runtime 回合都只让 full `state_keeper` 作为唯一 LLM 记忆写回者，输出增量 patch，再由 deterministic merge / normalize / canonicalize 层提交。统一模式下，skeleton keeper LLM、actor registry LLM、focused possession retry LLM、event ledger LLM、summary chunk LLM 都不再参与本轮写回，避免多个模型各自解释同一轮剧情。
- **state keeper fill**：统一事务模式下每个完整回合运行；legacy 模式下仍可按 `memory.consolidate_every_turns` 调度。fill 补充 scene_objective、signals、objects、knowledge_scope，以及有正文证据的 NPC 与主角关系标签。当 keeper 输出 `finish_reason=length` 时，本轮 keeper 结果视为失败，不允许半截 JSON 落盘。
- **actor registry**：统一模式下只运行确定性绑定、alias 更新、knowledge/possession actor_id 绑定，不再调用 LLM 创建新 actor；legacy 模式仍可用 LLM 提取新角色候选。
- **event ledger**：统一模式下使用 heuristic event ledger，不复用 `state_keeper` 的 `main_event / signal` 作为事件摘要，避免旧的 keeper_signals shortcut 造成空洞或重复事件摘要。legacy 模式仍可调用 event ledger LLM。
- **summary chunks**：统一模式下新 chunk 用 heuristic fallback 生成，保留原始 turn pair 细节，避免长程摘要 LLM 再次引入人物名漂移。legacy 模式下若 chunk LLM 返回 `finish_reason=length`，也会降级为 heuristic chunk 并记录 `llm_rejected_reason=length`。
- **opening choice**：选择开局进入首个 narrator 回合时不再先保存一次 pre-keeper state；最终 opening turn state 由 handler 在 keeper、arbiter、thread、actor 绑定和维护层之后统一提交。

名称规范化只在 actor_registry 绑定后由 `memory_maintenance` 统一执行一次，state_keeper 内部不再做独立的 semantic_cleanup。归一化层会优先使用 actor registry 的稳定 `name / aliases`，把 `scene_entities`、`important_npcs`、`active_threads.actors`、物件持有者和可见性名单里的描述性称呼收敛到同一 canonical NPC；同一 canonical 下的重复 scene/important 记录会合并，避免“药铺年轻男人 / 年轻男人”“背纹灵貂 / 灵貂”这类称呼变化继续分裂事实面。裸服务称呼（如 `掌柜`、`老板`、`伙计`）不作为跨场景 alias 使用，必须保留 `茶馆掌柜`、`药铺掌柜` 这类场景限定称呼，防止不同店铺人物互相串线。`context_builder` 在注入 summary chunks 前还会 quarantine 明显的主角名复合漂移（如“主角名 + 多余字”的伪人物名），并在 `context_audit.quarantined_summary_chunks` 中记录原因，防止旧坏 chunk 继续进入 narrator prompt。

Persona 写回的职责边界：`persona_updater` 负责人物 seed 的 scene/archive/longterm 流转、重要度计数与近期观察沉淀。NPC 是否值得保留 persona seed 的判断优先依赖 `important_npc_tracker` 的锁定结果，辅以出场连续性和用户关注度启发式。`actor_registry` 仍负责不可变人物基础设定，不应被 persona 的短期观察覆盖。Persona observation 只提供最近表现/关系压力/表达层风格的轻量提示，不能替代角色卡或 actor registry。外貌、语气、习惯动作和性格表现只从 assistant 正文中抽取，不读取用户 prompt 原文，也不让 narrator 直接提交 JSON sidecar。

NPC 与主角关系由 fill keeper 通过 `npc_relationships` 只输出本轮增量，如 `初识 / 相知 / 好友 / 队友 / 盟友 / 敌对 / 戒备`。该增量必须来自 narrator 正文里的可见互动、明确承诺、共同经历或冲突结果，不能因为玩家单方面声称关系成立就写入。提交阶段由 actor registry 把合法关系绑定到既有 NPC actor 的 `relationship_to_protagonist`，再由 narrator 的 `【角色注册表】` 注入；顶层 `npc_relationships` 只是临时 patch，不作为长期 state 列表保留。

物件状态采用“本轮明确事实覆盖旧账本”的口径。fill keeper 若看到已有物件被重新包好、放下、转交、收起或换位置，应输出同一 `object_id` 的最新 `possession_state`；归一化层会按 `object_id` 合并，并在当前场景已经显示主角携带/收起某物时，清掉明显过期的旧场景落点（如仍写在水里、桌上、床边），避免旧位置继续污染下一轮。


`tracked_objects` 支持 `aliases` 字段：当 narrator 正文中出现物件的昵称或简称（如主角给物件起的名字），fill keeper 会将其记入 `aliases` 数组。selector 和 `_is_object_heavy_turn` 在匹配物件时同时检查 label 和 aliases，确保即使 narrator 使用别名也能正确触发物件相关逻辑。aliases 只记录稳定的专有称呼，不记录代词或集体名词。
事件摘要不是新的剧情事实来源，只把已经出现在 narrator 回复头、当前 state 或本轮正文中的事实结构化保存。`event_summaries[].time_anchor` 先作为 selector 索引；命中后才进入 narrator prompt 的 `【命中事件索引】`，提醒模型按事件自身时间承接旧事。缺失时间只表示未记录，不允许模型自行补成“昨天/刚才”。`summary_chunks[].time_start/time_end` 记录固定窗口的起止叙事时间，仅作为归档 fallback；普通回合不再默认注入固定 12 轮外历史。

`scene_objective` 是当前事件/场景段的稳定目标，区别于每轮可变的 `immediate_goal`。它回答“这一段事件为什么存在、围绕什么测试或推进”，例如训练段的资源争夺、规则理解或风险控制；`immediate_goal` 仍只表示主角下一拍要处理的事。fill keeper 只在目标缺失、明确新事件开启或旧事件明确结束时更新；普通对白、观察、移动和短暂心理变化应沿用当前目标。narrator 只读取 active objective，用它约束本轮不要偏离事件主轴。

输出：
- 新的 `state`
- 新的 `summary`
- 新的 `persona state`

### Step 8. 返回前端

返回：
- reply
- state snapshot
- 调试信息（可选）

### Regenerate latest narrator turn

用户对最后一条 narrator 输出不满意时，前端可以调用 `/api/regenerate-last` 并传 `allow_complete=true`。该流程不是新增用户回合，也不改写用户输入；它只替换最新 `user -> assistant` 对里的 assistant/narrator 输出。

完整回合 regenerate 必须先用最新 turn trace 的 `pre_turn` 快照回滚旧 narrator 输出造成的事实层影响：

- `state.json` 恢复到该轮 narrator 生成前
- session-local `persona/*` 恢复到该轮生成前
- 删除该 turn 的 `event_summaries` 项
- 清空 `summary_chunks` 与 `keeper_record_archive` 派生缓存，避免旧输出继续参与 selector/context
- 用回滚后的 history/state 重建 `summary.md`
- 清理指向旧 turn response 的幂等缓存与 audit

回滚后再用同一条用户输入重新进入主链。最终 history 仍保持一条原 user，后接新的 assistant。若最新 turn trace 缺失，完整回合 regenerate 会拒绝执行，避免只替换 history 而留下污染的事实层。

当前 regenerate 回滚先清理 state/persona/event/summary chunk/keeper archive 等派生物，再重新进入 `handle_message()`；若新生成失败，会用进入 regenerate 前的快照恢复。该恢复不是跨文件数据库事务，依赖各 artifact 的原子写入与失败回滚逻辑。

### Delete latest user turn

用户误触发送、输入错别字或内容未写完时，前端可以调用 `/api/delete-latest-turn` 撤销最后一轮。该流程只允许删除最新 `user -> assistant` 对，不支持删除历史中间轮次。

完整回合 delete 与 regenerate 使用同一套 turn trace 回滚原则，但不会重新进入 `handle_message()`：

- `history.jsonl` 删除最后的 user/assistant 对
- `state.json` 恢复到该轮生成前的 `pre_turn.state`
- session-local `persona/*` 恢复到该轮生成前的 `pre_turn.persona_layers`
- 删除该 turn 的 `event_summaries` 项
- 按删除后的 pair count 修剪 `summary_chunks` 与 `keeper_record_archive` 派生缓存，保留更早的合法 summary / keeper 记录，避免误触输出继续参与 selector/context
- 用删除后的 history/state 重建 `summary.md`
- 清理指向该 turn 的幂等缓存与 audit，并回退 `meta.last_turn_id`

如果最新完整回合缺少 turn trace，delete 会拒绝执行，避免只删除可见聊天记录但保留 keeper/state 污染。

---

## Backend Handler 顺序

`POST /api/message` 在 backend 内部建议按这个顺序执行：

1. 校验请求体
2. 解析 `session_id`，确认它属于当前角色卡作用域；若同名 session 存在于其他角色卡下，拒绝请求
3. 按解析后的 session 路径加锁
4. 检查 `(session_id, client_turn_id)` 是否已处理
5. 调 runtime `handle_message(payload)`
6. runtime 返回 `reply + state_snapshot + debug`
7. backend 写访问日志 / 模型 usage
8. 返回 JSON 给前端

---

## 最小 Runtime Handler 伪代码

实际函数名是 `handle_message(payload)`；下面的 `handle_turn` 只是早期概念名，后续实现和文档应以 `handle_message` 为准。

```python
def handle_message(payload: dict) -> dict:
    session_id = payload["session_id"]
    text = payload["text"]
    meta = payload.get("meta", {})
    ctx = load_runtime_context(session_id)
    scene_facts = build_scene_facts(ctx)
    user_turn = analyze_user_input(text, scene_facts)

    arbiter_result = None
    if user_turn.arbiter_needed:
        arbiter_result = run_arbiter(user_turn, scene_facts, ctx)

    narrator_input = build_narrator_input(
        ctx=ctx,
        scene_facts=scene_facts,
        user_turn=user_turn,
        arbiter_result=arbiter_result,
    )

    reply, usage = call_model(narrator_input)

    write_history(session_id, text, reply)
    update_state(session_id)
    update_summary(session_id)
    update_persona(session_id)

    return {
        "reply": reply,
        "usage": usage,
        "state_snapshot": build_state_snapshot(session_id),
        "debug": build_debug_snapshot(session_id, user_turn, arbiter_result, meta),
    }
```

---

## 关键约束

- `handle_message()` 必须是 runtime 唯一主入口；`handle_turn` 仅作为旧文档/伪代码概念名存在
- `runtime-rules.md` 必须在每次 `handle_message()` 构建 runtime context 时优先加载
- 前端不要自己拼 prompt
- backend 不要自己判定剧情
- 模型调用层不要自己维护长期状态
- 所有写回必须发生在同一条 turn pipeline 中，避免状态分叉；当前实现不是跨 artifact 事务，`state/history/summary/event/persona/trace` 依赖原子文件写入和 regenerate 失败快照恢复来降低半提交风险
- 刷新策略当前采用“每轮轻刷新 + keeper fill 周期刷新 + 12 轮 summary chunk / selector 锚点召回”；事件触发深刷新是设计目标，尚未形成独立 20 轮调度器

## 最小内部对象

建议围绕一个 `TurnEnvelope` 运行：

```json
{
  "session_id": "story-001",
  "turn_id": "turn-0042",
  "user_input": "用户输入",
  "scene_facts": {
    "time": "...",
    "location": "...",
    "main_event": "...",
    "onstage_npcs": ["..."],
    "relevant_npcs": ["..."],
    "immediate_goal": "...",
    "immediate_risks": ["..."],
    "carryover_clues": ["..."]
  },
  "persona": [],
  "recent_history": [],
  "arbiter_needed": false
}
```

## 核心原则

- `state` 比 transcript 更重要
- recent window 比一切软摘要更重要
- keeper archive 比自由历史检索更重要
- `persona` 是运行时骨架，不是展示文本
- 世界书人物默认优先进入因果链，而不是突兀肉身进场
- `chat history` 只是辅助，不应成为唯一真相源

## 2026-05-03 运行行为更新

- keeper/event：event summary 由事件账本基于最近 1~3 对 turn 生成，保留阶段经过、风险/线索和 `scene_shift`；不再把 keeper `main_event` 当作唯一 summary 来源。
- keeper/state：`carryover_signals / immediate_risks / carryover_clues` 会过滤过短、过长或明显残缺的碎片，避免脏 clue 继续污染 thread / selector。
- thread：main 线程继承必须有 goal / label / signature 连续性；仅地点相同不会继承旧 `stability_turns`。
- selector：summary chunk 的 `keywords` 应优先保存稳定检索键：人物名、地点名、关键物件、事件短语、关系线。turn audit 会记录 `npc_profile_load`，包括目标、实际加载、缺失项与 profile 目录，用来诊断 profile target 和 narrator 注入之间的断链。
- narrator：若最近几轮已经反复停在观察、判断、沉默、不点破、目光变化或心理揣测，本轮必须推进一个客观可感知的新变化；用户输入只做轻承接，正文主体应写用户动作之后世界如何回应。

## 2026-05-05 Keeper / Selector 质量修复

- keeper/thread：risk / clue thread 去重时，若更具体的 `label` 覆盖旧标签，必须同步重算 `key`，避免出现 `key` 仍指向旧风险、`label` 已变成新风险的状态污染。
- keeper/signals：fill keeper 可输出 `resolved_signals`，用于显式关闭本轮已经完成检查、解除风险或落地的旧信号。`normalize_state_dict` 会在 thread tracker 前过滤对应的 `carryover_signals / immediate_risks / carryover_clues`，避免 stale risk 每轮复活。
- keeper/state：active thread 的 `actors` 会对齐 actor canonical name，并按 thread 文本与当前 `main_event / risks / clues / signals` 剪枝；旧场景 NPC 不再因为 thread 冷却而继续粘在当前 thread actor 索引上。
- keeper/state：`relevant_npcs` 只从当前信号层保留明确命中的 offstage 稳定人物；active thread 文本本身不再反向回填 relevant，避免旧 thread 把已离场 NPC 重新推回 selector 视野。
- keeper/state：当前 `time` 只保存粗时段；narrator header、skeleton keeper 和 state normalization 都会把具体钟点收敛到清晨/上午/中午/下午/傍晚/晚上/夜里。精确钟点只作为预约、截止或倒计时保留在目标、信号和 thread 文本中。
- keeper/knowledge：非 full keeper turn 也会补一层轻量可见知识 delta。当前先覆盖本轮 narrator 明确写到的可见物件持有状态，再交给 actor registry 折叠进 `knowledge_records`。
- selector/event：event recall 不再只按 topic overlap + NPC 名加分；现在更偏向当前 `user_text / location / main_event` 命中的事件，并用 recency bonus 与同分新 turn 优先减少旧事件机械回流。
- selector/event：高频反复出现的 carryover clue 会降权，避免同一个旧 clue 让 `evt_0002/0003/0004` 之类早期事件长期占据召回位。
- lorebook audit：`lorebook_injection.total_chars` 只代表候选 summary 体量，不再被当作有效注入总量。turn audit 额外记录 `selected_summary_chars / source_hit_chars / index_hit_chars / foundation_chars / effective_total_chars`，用于区分“没有 selected summary”与“仍有 foundation/source/index 实际入 prompt”。

## 2026-05-08 Long-session Memory Maintenance

长 session 的问题不只在“记录不够”，还在于既有记录需要持续维护。当前 runtime 已加入一层 deterministic memory maintenance；每轮提交中维护 state 内的实名揭示和旧风险关闭，离线 repair 可额外清洗 / canonicalize 派生 archive：

- actor canonicalization migration：`actor_registry` 一旦通过窄口径实名揭示把 generic actor 绑定到主名，`memory_maintenance.py` 会在每轮提交中把 state 中的 `onstage_npcs / relevant_npcs / scene_entities / active_threads / important_npcs / possession_state / object_visibility / knowledge_scope.npc_local` 对齐到 canonical name；离线 repair 还会同步 `event_summaries / summary_chunks / keeper_record_archive`。该迁移只使用 registry 里已经存在的精确 alias，不从正文推断新等价关系；如果多个 actor 共享同一 alias，该 alias 会被跳过，避免误合并人物。
- stale risk/thread resolver：当某个 actor 已经在 `onstage_npcs`，而旧 signal/thread 仍写着“仍在门外等待 / 还在门外等待 / 在走廊等待”等明确等待模式时，runtime 会剪掉对应 `immediate_risks / carryover_clues / carryover_signals`，并把纯 stale risk thread 归档为 resolved；如果只是主线程的 `obstacle` 过时，则只清空 obstacle，不删除主线。
- keeper archive validation / recall filtering：keeper archive 是派生缓存，构建和读取时都会经过 `validate_keeper_archive()`。验证会删除非 object、窗口越界、空内容和已知 fragment digest；`provider == "manual-cleanup"` 的人工记录受保护。过滤只针对短碎片和明确坏 digest 模式，避免把有意义的“不确定/否定”事实误删。
- archive / summary repair command：`backend/tools/repair_session_memory.py` 可对既有 session dry-run 检查或显式 `--apply` 写回。默认不写 state / summary chunks / event summaries / keeper archive；`--rebuild-derived` 才会重建派生层，`--no-archive-write` 可禁止 archive 写回。

完整 turn 提交流程中，state maintenance 在 `update_actor_registry()` 之后、最终 `save_state()` 之前运行，并把本轮维护结果写入 turn trace 的 `post_turn.memory_maintenance`，便于确认哪些字段被 canonicalize 或 stale-pruned。`event_summaries / summary_chunks / keeper_record_archive` 的派生层 canonicalize 仍属于 repair / rebuild 范围，不是普通每轮提交的一部分。

## 2026-05-09 Low-pressure Turns and False NPC Filtering

针对长跑 session 中“低压动作被强行写成悬疑压力”和“时间/栏目/盲区等抽象概念被注册成 NPC”的问题，runtime 进一步收紧以下边界：

- 低压动作保持低压：看书、休息、坐下、发呆、晒太阳等普通动作不会轻易触发 stealth arbiter；即使存在弱观察，也默认落到 clue 层，不再自动写成 immediate risk。
- narrator 输入在低压休整/看书场景中明确禁止擅自引入新的可疑脚步、暗门、钥匙声、窥视者、反光物或追踪者；旧风险只能轻触背景，不能覆盖当前低压动作。
- `actor_registry / state_bridge / persona_updater / selector / summary_chunks` 共用更严格的人物名质量门槛，抽象话题、栏目名、时间概念、标题残片和地点/物件碎片不能创建 actor、scene entity、persona seed、NPC profile target 或 summary chunk actor metadata。
- `onstage_npcs` 不再因为 actor registry、important NPC 或旧 thread 存在就自动保留。场景已切换或当前 hard anchor 没有本轮人物证据时，旧核心 NPC 会从 onstage 清掉；keeper validation 允许有新 location/main_event 信号的空 onstage 结果。
- event actor attribution 只在 summary/clue 文本当前确实提到该人物时写入，不再无条件把 state 里的 onstage NPC 贴到每个事件摘要上。

## 2026-05-15 Subtractive Long-session Stability

本轮修复目标是减轻 keeper 和 selector 对长 session 的放大效应，而不是增加新的长期记忆层或角色卡/session 专属关键词。

- header / event 分离：markdown header、日期、时间、地点行只作为 metadata。即使是非公历风格的纪年，只要没有具体动作，也不能写成 `main_event`；归一化会优先保留上一条有效事件或后续动作句。
- current-turn participant 保留：skeleton/current-turn `onstage_npcs` 是当前回合人物证据，必须能穿过 skeleton-only 与 full keeper baseline；最终持久化 state 会移除私有 `_current_turn_onstage_npcs` marker。
- keeper fill 减权：full keeper 只补 `scene_objective / signals / objects / knowledge_scope` 等增量 patch，不应覆盖 `time / location / main_event / onstage_npcs / immediate_goal` 这些已由 fragment/skeleton 固定的核心场景字段。
- active object lifecycle 收窄：只有仍可行动的物件留在 `tracked_objects`，例如被携带、收起、放在可交互位置、部分消耗后保存、转交给他人或作为证物/工具继续存在。一次性吃完、花掉、背景描写里出现但没有持有/落点的普通物件不进入 active tracker；退出追踪的物件写入 `graveyard_objects`。
- selector 对日常物件召回降噪：普通“吃饼/拿水/买东西”这类弱日常物件词不会单独触发 12 轮外 event / summary 大量注入。若存在 active tracked object，优先通过 `【重要物件与持有关系】` 进入 narrator；否则依赖最近完整正文和本轮输入，不靠旧摘要猜来源或数量。
- narrator 物件细节约束：物件来源、剩余数量、当前位置、谁看见过/知道它，必须来自最近正文、本轮用户输入或注入的物件/知情证据；没有证据时只能模糊承接，不得编造购买地点、食用进度、存放位置或旁观者知情。
- summary chunk 名称一致性：固定 12 轮摘要在归一化时会用源窗口中出现过的主角名修复一字漂移，避免“主角名错字”被写进 `dense_summary / key_events / actors_mentioned / keywords` 并成为后续召回锚点。

调试面板对应观察点：看 `Prompt Blocks` 是否有 `【重要物件与持有关系】`、`【命中事件索引】` 或 `【召回的归档提纲】`，看 selector 的 `event_hits / summary_chunk_hits / inject_summary` 是否被当前强锚点触发。普通物件名、低压休息/等待/移动动作不应单独召回旧历史；若 `event_hits` 已覆盖同一主题，宽泛 summary chunk 通常应被压制。

## 当前 persona 门槛

- 默认连续 5 轮稳定出现，才自动进入 `scene persona`
- 默认连续 7 轮稳定出现，才自动升到 `longterm persona`
- 无专名服务型 NPC 默认不自动建 persona
- 以下情况允许提前进入 `scene persona`：
  - 用户连续关注
  - 世界书既有重要人物，且已进入当前局势
  - 线索承载者 / 可疑当事人 / 当前异常变量承载者
- 若线索减弱，但人物仍在持续互动，则先保留
- 若场景切换，且连续 2 轮无互动，则降到 `archive`

## Entity 读取原则

前端在显示 NPC 时可以用 `primary_label`，但 runtime 内部应优先围绕 `entity_id` 工作。

原因：
- 同一个人物可能经历称呼演化
- 同一个称呼也可能在不同场景复用

因此：
- `Onstage NPCs` / `Relevant NPCs` 是给前端看的主称呼层
- `Scene Entities` 是 runtime 的中间身份层
- `GET /api/entity` 返回的是只读调试视图，不是编辑入口
