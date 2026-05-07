# Context Flow

**当前版本：v1.0**

## 旧链路

```text
online session
  -> transcript
  -> history sync
  -> state / summary 提炼
  -> prompt build
  -> narrator
  -> 新 transcript
```

问题不在“有没有 state / summary”，而在：
- transcript 既是输入来源，又不断吸收输出结果。
- prompt 最后仍会把 recent history 大块拼回去。
- 长时间运行后，模型更容易延续自己刚写出的文本惯性，而不是回到运行态文件。

## 新链路

```text
web input
  -> runtime handler
  -> runtime rules
  -> card / preset / lore / canon / state / persona / recent window / keeper archive
  -> narrator
  -> skeleton keeper / state keeper fill
  -> optional summary writer
  -> session-local state / summary / history
```

关键差异：
- `runtime-rules` 与当前角色卡世界设定是 narrator 的最高约束；`state` 是当前场景的结构化承接层，`summary` 不再是 narrator 主输入。
- `history` 只保留最近窗口承接，不再承担完整骨架职责；narrator 现在用“最近完整正文 + 前段逐回合提纲”桥接同一窗口内较早回合，避免大段 prose 淹没关键事实。
- 更早历史优先收敛成 keeper archive，而不是自由摘要层。
- 写回时先收口到结构化状态；`summary` 可继续保留为调试/运维产物，但不再主导 narrator。
- state 写入分三类：opening 只做开局状态机 checkpoint；`handler_message.py` 负责每个完整 turn 的最终权威提交；keeper archive 写入只维护派生缓存。
- keeper 写回按增量 patch 执行：骨架字段由 skeleton keeper 维护，fill keeper 只补信号、物件、持有关系、可见性和本轮知情 delta。
- `knowledge_scope` 是本轮 delta，长期知识落到 `knowledge_records`；物件退出 active 状态通过 `lifecycle_status` 和 `graveyard_objects` 表达。
- keeper archive 是派生缓存，刷新时会清理超过当前有效 pair index 的未来 records，避免撤回/重试后的旧分支污染召回。
- keeper archive 的读路径默认允许维护派生缓存；需要只读检查时，调用方可通过 `allow_archive_write=False` 禁止 prune/rebuild 落盘，默认运行行为不变。
- narrator 输入会注入“世界设定锁”：本轮用户输入只表达主角当前行动/对白/意图，不能切换主世界题材；召回历史、世界书候选或用户输入若与当前角色卡世界不兼容，只能在当前世界观内转译或收束。
- 防污染判断不靠固定关键词表。不同角色卡的题材边界差异很大，运行时提示要求按整体语境、因果规则、时代感、社会制度、技术/超自然边界和人物身份兼容性来判断是否承接候选内容。
- runtime fallback / bootstrap 的词表只允许使用通用职能词、通用地点后缀和通用物件类别；不应把某张角色卡的固定人名、组织名、session id 或剧情专属物件写进生产逻辑来强化表现。
- 同一层还负责用户控制权边界：用户主角只是世界内角色，不是作者、导演、GM 或世界主宰。用户输入只能提出尝试，不能直接决定 NPC 服从、行动成功、关系成立、物品归属、场景改写或客观结论；这些必须由当前世界的因果、资源、制度和 NPC 反应结算。
- NPC profile 注入分两级：source markdown profile 是强档案；当前 session 的 persona seed 是兜底档案。兜底内容只包含身份、persona hooks 和 assistant 叙事中观察到的短片段，不能从用户 prompt 原文生成 NPC 事实。
- 角色注册表的基础字段默认不可变；实名揭示只作为 alias-upsert 处理。当“剃寸头的高个子学员”这类稳定 generic actor 后续明确自报姓名或被点名时，runtime 可把实名追加到该 actor aliases，用于后续 knowledge/profile/selector 绑定，但不重写原基础设定。
- `relevant_npcs` 只保留有正向人物证据的名字；当当前 `main_event` 或连续性文本提到一个不在 onstage 的重要人物 / actor / scene entity 时，可以把它保留为 relevant，以便 selector 后续召回，但不能从地点、标题残片或 active thread 文本反推虚假 NPC。

当前分工草案（设计目标，不代表所有实现都已完全收口）：
- `signals`：当前方向约束层。用于承接后续仍会影响局势推进的 `risk / clue / mixed` 信号，可直接进入 narrator / selector。
- `event`：中短程提纲 / 检索层。每轮 event summary 既供 selector recall，也可作为 recent window 前段提纲直送 narrator，用于承接最近完整正文外的几轮事实；它不是要求 narrator 逐条复述的 steering 块。
- `summary`：长程压缩层。默认只在 selector 判断 recent window 不足、且旧事件确实回流时才补给 narrator。
- `thread`：当前实验中已开始降级为 state/debug 辅助层，不再默认主导 narrator 或 selector。

更具体地说：
- narrator 主导“当前这轮怎么写”，不由 `thread` 或 `event` 直接接管。
- selector 主导“这一轮要不要把旧东西拿回来”，优先参考 `recent window + state + signals + event recall`。
- 世界书由三层处理：开局首个 narrator 回合用原始 alwaysOn/foundation 条目大预算定底；后续每轮常驻蒸馏出的基础护栏；selector 命中世界书 index 后回源到原始 `lorebook.json` 片段交给 narrator，而不是只给蒸馏摘要。
- keeper 主导“后台结构化维护世界状态”，其中：
  - `signals` 负责“当前还没消失、会继续影响下一拍”的东西；
  - `resolved_signals` 负责显式关闭本轮已经解决的旧风险或旧线索，关闭发生在 thread tracker 重建前；
  - `knowledge_scope` 只负责本轮新增知情 delta，长期情报由 `knowledge_records` 承担；
  - `objects` 负责 active 物件、持有关系、可见性和生命周期退出；
  - `event` 负责“前几轮到底发生了什么值得检索”；
  - `summary` 负责“更长阶段该如何压缩”；
  - `thread` 若保留，也更偏 debug/state 辅助，而不是 steering 层。
- keeper archive 的中程 digest 应优先从窗口正文自身提取时间、地点、持续人物、持续事件和物件，而不是复用当前 state 的硬锚点。窗口中可用的 NPC registry 名字会参与稳定人物识别，避免 archive 只留下“围绕某地持续演化”这类低密度事件句。
- 当前 event 链已开始按这个方向实现：事件总结默认读取最近 `1~3` 对 turn 窗口，并在 narrator recent window 中作为“前段提纲”承接完整正文之外的较早回合；selector 仍可把它作为 recall / summary 的前置材料使用。
- 当前 selector 的 event recall 会优先 current-scene 命中和较新事件；同 NPC、同旧 clue 只能作为弱辅助信号，不能长期压过当前地点/动作/主事件。
- lorebook audit 分为候选摘要、source hit、index hit、foundation 和 effective total 五类字符统计。调试时应看 `effective_total_chars` 判断实际入 prompt 体量，而不是只看 `total_chars`。

## 2026-04-28 Keeper / Selector 稳定性修复

针对 `维克托奥古斯特-20260428-f773f2` 的检查结果，已收紧以下运行链路：

- 用户继续输入时，若 history 尾部仍是 `completion_status=partial` 的 assistant 回复，会先移除该半截回复再追加新 user turn，避免 partial 文本污染 keeper / selector。
- keeper archive 构建 turn pairs 时只接受 complete assistant 回复；partial assistant 会关闭当前 pair，不进入 archive 统计和摘要。
- state keeper fill 的用户提示明确要求输出必须以 `{` 开头、以 `}` 结尾；非空但不可解析的输出会自动重试一次，并在重试提示中禁止解释、代码块和 JSON 前后文字。
- selector 现在会基于 state、recent window、user text 对 `event_summaries` 做 topic/actor overlap 命中，`event_hits` 不再固定为空。
- summary chunk 命中增加轻量 topic overlap 兜底，并在命中结果里保留 `keyword_hits` 便于 trace 诊断。

这组修复的目标不是扩大 narrator 输入，而是保证 recall 层只带入可用、完整、与当前 query 相关的历史材料。

## 2026-05-03 Narrator / Keeper / Selector 运行修复

针对 `维克托奥古斯特-20260502-ce22a3` 的检查结果，runtime 收紧以下行为：

- event summary 不再只用 state keeper 的 `main_event` 直接写入；完整 turn 提交后会用事件账本读取最近 1~3 对 turn，生成更像阶段经过的 `summary_text`，并把 `scene_shift` 写入 event summary。
- `scene_shift` 对明确地点变化更敏感：只要上一地点与当前地点都稳定且发生变化，即使 NPC 列表没有大换血，也会标记场景切段。
- carryover signals / risks / clues 增加短碎片过滤，避免“惹了涂”这类残词进入 clue 层并污染 selector。
- active thread 的 main 线程匹配更保守；地点相同不再足以继承旧线程，必须有 goal / label / signature 的实际连续性，避免新事件继承旧 `stability_turns`。
- summary chunk keywords 改为结构化检索键，优先人物、地点、物件、事件短语和关系线，而不是随机中文碎片。
- selector audit 现在记录 `npc_profile_load`，包括请求的 profile targets、实际加载项、缺失项、profile 目录和失败原因，便于定位“selector 有 target 但 narrator 无 profile”的断链。
- selector 的 NPC profile 读取现在会在 source markdown profile 缺失时回落到 session persona seed。audit 中 `loaded` 可因此包含来自 session persona 的人物；若 target 仍缺失，才说明 source 与 session persona 均没有可用档案。
- narrator prompt 增加重复观察抑制：若最近几轮已反复出现“观察—判断—不点破/沉默”等镜头，本轮必须推进可感知的外部变化，而不是扩写用户输入或换词重复心理观察。

## 2026-05-07 NPC Profile / Persona / Archive 修复

针对 `bd4769` 一类长跑中“NPC 详情仍停在初始骨架”的问题，runtime 补上以下链路：

- `load_npc_profiles()` 在 source `.md` profile 缺失时，会读取当前 session 的 `persona/scene`、`persona/longterm`、`persona/archive` JSON seed，并格式化为 narrator 可读的轻量 profile。
- `persona_updater` 现在把 NPC 相关的近期 assistant 叙事片段写入 `observations`，用于记录最近行为和关系压力；不读取用户 prompt 原文，不把同一片段重复写入多个 observation 字段。
- keeper archive 构建窗口 digest 时会把 NPC registry 传入 mid-context heuristic，提升 stable_entities 与 ongoing_events 的信息密度。
- state normalization 会在当前 `main_event` / continuity 文本提到非 onstage 的稳定人物时，把它保留在 `relevant_npcs`，避免场景相关 NPC 因未站在前台而从 selector 视野消失。

## 当前 Threadloom 的建议优先级

1. 先稳 `state`。
2. 再稳 `recent window -> keeper archive` 的两层上下文。
3. 再接入 arbiter / persona 流转。
4. 最后再继续打磨 UI。
