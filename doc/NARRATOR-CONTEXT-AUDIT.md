# Narrator Context Audit

这份清单用于审计 `Threadloom` 当前 narrator 每轮实际吃到的上下文块，目标不是简单缩短 prompt，而是：

- 明确哪些块必须常驻
- 明确哪些块属于 continuity 补充
- 明确哪些块只是候选知识，正在稀释正文推进
- 为后续“保留 / 压缩 / 条件注入 / 移出主链”提供逐块操作依据

## 审计原则

- narrator 目标是维持一个会自己流转的 RP 世界，主角是参与者与观察者，不是唯一驱动器
- 不轻易削弱事实边界、主角控制权、canon/state 约束
- 优先削弱的是：同权重杂音、候选知识的常驻注入、以及会把 narrator 推成“谨慎摘要器”的块

## 当前装配入口

- 组装位置：`backend/narrator_input.py`
- 来源汇总：`backend/context_builder.py`
- 条件注入调度：`backend/selector.py`
- 长期底板：`prompts/runtime-rules.md`

## 审计表

### 1. Runtime Rules

- 区块：无标题，直接拼入 system prompt 顶部
- 来源：`prompts/runtime-rules.md`
- context key：`runtime_rules`
- 当前状态：每轮常驻
- 价值：极高。定义主角控制权、知情边界、世界自主流转、推进规则
- 风险：措辞过强时，会把 narrator 推向保守执行器
- 当前建议：保留
- 后续动作：逐条做“删 / 改弱 / 保留”审计，重点关注过多的负面约束语气

### 2. 预设框架

- 区块：`【预设框架】`
- 来源：当前 active preset 的 `system_template`
- context key：`active_preset.system_template`
- 当前状态：每轮常驻
- 价值：中高。为不同题材和运行风格补充世界模拟框架
- 风险：可能与 runtime rules 重复、叠加同类约束
- 当前建议：保留
- 后续动作：检查和 `runtime-rules.md` 的重复约束，必要时去重或收短

### 3. 角色核心

- 区块：`【角色核心】`
- 来源：`character-data.json`
- context key：`character_core`
- 当前状态：每轮常驻
- 价值：高。定义当前角色卡世界、叙事框架、主角与世界的基本关系
- 风险：若内容过长、字段过全，会稀释当前场景
- 当前建议：保留
- 后续动作：评估是否需要再做 runtime slim 版，而不是每轮全量 JSON

### 4. 玩家档案

- 区块：`【玩家档案】`
- 来源：用户基础设定 + 当前角色卡强化设定
- context key：`player_profile_md` / `player_profile_json`
- 当前状态：每轮常驻
- 价值：高。保证主角气质、能力、世界适配稳定
- 风险：若再次膨胀成长版设定，会抢走正文空间
- 当前建议：保留
- 后续动作：继续维持 runtime slim 版，不回退到长人物小传

### 5. 长期事实 canon

- 区块：`【长期事实 canon】`
- 来源：角色卡 canon
- context key：`canon`
- 当前状态：每轮常驻
- 价值：极高。是长期事实与已发生后果的硬边界
- 风险：若 canon 自身过长，会拖 prompt；但当前不宜先动
- 当前建议：保留
- 后续动作：如有需要，先做 canon 内容治理，不先从 narrator 侧砍

### 6. 当前硬锚点

- 区块：`【当前硬锚点】`
- 来源：`scene_facts`
- context key：`scene_facts.time/location/onstage_npcs/relevant_npcs`
- 当前状态：每轮常驻
- 价值：极高。当前镜头的最强事实边界
- 风险：措辞过于绝对时，容易压制 continuity 与自然延展
- 当前建议：保留
- 后续动作：保留块本身，但后续可评估是否把“一律以这里为准”的语气收柔一点

补充：
- `immediate_goal` 已从 narrator 主链降级，不再作为常驻锚点直接塞给 narrator
- narrator 主要依靠最近 12 轮、当前硬锚点与 active_threads 自行判断眼前应如何续接

### 7. 知情边界

- 区块：`【知情边界】` + `【知情边界补充】`
- 来源：`knowledge_scope` + 固定规则
- context key：`scene_facts.knowledge_scope`
- 当前状态：每轮常驻
- 价值：极高。防止 narrator 乱泄露信息
- 风险：容易把 narrator 推向“最安全的少写”
- 当前建议：保留
- 后续动作：事实边界不删，但可补“NPC 仍可基于可见动作与外部痕迹做有限反应”的正向规则，弱化其抑制感

### 8. NPC Roster

- 区块：`【NPC Roster】`
- 来源：selector 生成的轻量 roster
- context key：`npc_roster`
- 当前状态：每轮常驻
- 价值：中高。帮助 narrator 维持当前值得记住的人物边界，但不再承担全量别称映射职责
- 风险：若 selector 打分过宽，仍可能把边缘人物长期挂进 roster
- 当前建议：保留
- 后续动作：继续维持最小字段集 `name / role / status`，优先治理 selector 召回质量，而不是把 registry 全量拉回 narrator

### 9. 最近窗口

- 区块：`【最近窗口】`
- 来源：recent history
- context key：`recent_history`
- 当前状态：每轮常驻
- 价值：极高。是当前连贯体验的核心
- 风险：措辞过于绝对，会让 narrator 只敢写眼前半步
- 当前建议：保留
- 后续动作：保留块本身，后续优先评估“冲突时服从、无冲突时允许自然吸收 continuity”的表达

### 10. 活跃线程

- 区块：`【活跃线程】`
- 来源：state 中的 `active_threads`
- context key：`scene_facts.active_threads`
- 当前状态：已从 narrator 主链降级，当前不再默认注入 narrator prompt
- 价值：中。仍可作为 state/debug 层观察当前 keeper 对局势的拆分方式
- 风险：若继续把它当 narrator 或 selector 的主导层，会和 `main_event / signals / recent window` 重复，甚至反向拖慢当前局势判断
- 当前建议：保留结构，但仅作为 debug/state 辅助层使用
- 后续动作：继续观察去主导化后的真实 session，若连续性不受影响，可再评估是否进一步削减 thread 层职责

补充：
- `main_event` 当前已改为低频维护：默认只在早期 turn、周期点或明显场景切段时允许高频链重写

### 11. 重要物件与持有关系

- 区块：`【重要物件与持有关系】`
- 来源：tracked objects
- context key：`scene_facts.tracked_objects / possession_state / object_visibility`
- 当前状态：每轮常驻
- 价值：中高。对物件驱动场景很重要
- 风险：在无物件压力的普通场景里可能抢注意力
- 当前建议：暂时保留
- 后续动作：评估是否改成“仅在当前场景真相关时常驻，否则条件注入”

### 12. 较早结构记录

- 区块：`【较早结构记录】`
- 来源：keeper recall
- context key：`keeper_records`
- 当前状态：当前每轮常驻
- 价值：高。补中程记忆和旧线回流
- 风险：这是当前最值得改成条件注入的 continuity 块之一
- 当前建议：保留，但后续优先评估“条件注入”
- 后续动作：触发条件可考虑改为“当前线程/当前 NPC/当前地点显式相关时再进”

### 13. 相关 NPC 档案

- 区块：`【相关 NPC 档案】`
- 来源：npc profile 文件
- context key：`npc_profiles`
- 当前状态：条件注入
- 价值：中高。能稳定说话风格和关系语气
- 风险：这是当前最重、最可能稀释正文推进的块之一
- 当前建议：已开始改成条件注入
- 当前规则草案：
  - 默认只给 `onstage NPC`
  - 若 `relevant NPC` 在最近窗口或 `active_threads` 中被明确提到，再补 1 到 2 个
  - `important_npcs` 只有在最近窗口被明确提及时才可补入
- 后续动作：继续观察目标数量是否过多，以及是否需要再加轻量 judge

### 14. Onstage Persona

- 区块：`【Onstage Persona】`
- 来源：persona seeds
- context key：`persona`
- 当前状态：每轮常驻
- 价值：高。帮助角色说话方式和冲突风格稳定
- 风险：相对可控，目前比 npc_profiles 更值得保留
- 当前建议：保留
- 后续动作：如后续压 prompt，优先保留它而不是保留长 npc_profiles

### 15. 系统级 NPC

- 区块：`【系统级 NPC】`
- 来源：角色卡系统人物候选
- context key：`system_npc_candidates`
- 当前状态：条件注入
- 价值：中。可帮助世界已有重要角色自然回流
- 风险：这是当前最值得改成条件注入的候选知识块之一
- 当前建议：已开始改成条件注入
- 当前规则草案：
  - 若存在 `onstage NPC`，可注入
  - 若 `relevant NPC` 在最近窗口或 `active_threads` 中被明确提到，可注入
  - 若 `important_npcs` 在最近窗口中被明确提到，可注入
  - 若候选人物名本身已经在 `recent_history / active_threads / important_npcs` 里真实命中，可注入
- 后续动作：观察命中率是否仍偏高；必要时再收紧

## 上游治理观察

最近已开始对 narrator 上游信号做收紧：

- `important_npcs`：提高泛称型人物进池门槛，并让离场后的泛称人物更快退出
- `active_threads`：开始避免 `risk/clue` 线程直接挂半句对白，改成更中性的线程标签
- `main thread`：开始通过本地 label composer 生成更接近“谁在对谁做什么 / 当前局势往哪条线走”的可演标签

当前效果：

- `important_npcs` 的泛称人物数量已开始下降
- `npc_profiles` 条件注入已经明显减负
- `main thread` 已开始从抽象风险词收回到更可演的局势标签，但仍需继续观察是否过于依赖泛称 actors

### 16. 可调入世界书 NPC

- 区块：`【可调入世界书 NPC】`
- 来源：世界书人物候选
- context key：`lorebook_npc_candidates`
- 当前状态：条件注入
- 价值：中。对旧线回流和势力接口有帮助
- 风险：高。容易让 narrator 进入“谨慎调用知识库”模式
- 当前建议：已开始改成条件注入
- 当前规则草案：
  - 与 `系统级 NPC` 共用一轮候选闸门
  - 若当前场景/最近窗口/active_threads 没有相关人物回流信号，则不注入
- 后续动作：继续观察是否仍有候选块过多的问题

### 17. 世界书正文

- 区块：`【世界书】`
- 来源：lorebook summary
- context key：`lorebook_text`
- 当前状态：条件注入
- 价值：中。能补世界规则、势力背景和解释性信息
- 风险：极高。是当前最可能稀释正文推进、把 narrator 拉成保守解释器的块之一
- 当前建议：已开始改成条件注入
- 当前规则草案：
  - 当前场景明显需要背景解释时注入
  - 当前地点与某条 world lore 有明确匹配时注入
  - 当前 thread / keeper record / recent window 已明确指向某条 lore 时注入
  - 普通安顿、回屋、观察、生活流过渡段默认不注入
- 后续动作：继续观察是否出现“该注入时没注入”的漏判

### 18. 推进规则 / 裁定结果 / 结构化状态锚点

- 区块：`【推进规则】` / `【本轮裁定结果】` / `【结构化状态锚点】`
- 来源：preset / arbiter / state fragment
- 当前状态：有条件注入
- 价值：高。属于当前链路里较健康的条件块
- 风险：相对可控
- 当前建议：保留
- 后续动作：暂不优先处理

### 19. 最终要求

- 区块：`【要求】`
- 来源：`backend/narrator_input.py` 固定尾块
- 当前状态：每轮常驻
- 价值：高。决定 narrator 的写作姿态
- 风险：这里的语气强度会直接把 narrator 推成“保守执行器”或“活世界叙事者”
- 当前建议：持续审计
- 后续动作：后面“删 / 改弱 / 保留”的逐条 prompt 工程，主要就要在这里和 `runtime-rules.md` 下手

## 当前优先级建议

第一优先：
- `【世界书】`
- `【系统级 NPC】`
- `【可调入世界书 NPC】`
- `【相关 NPC 档案】`

第二优先：
- `【活跃线程】`
- `【人物连续性表】`
- `【较早结构记录】`

第三优先：
- `【最近窗口】`
- `【知情边界】`
- `runtime-rules`

## 当前结论

现在 narrator 质量问题更像：

- 不是单纯“prompt 太长”
- 而是有太多不同来源的块在以近似同权重对 narrator 发号施令
- 其中最值得优先清理的，不是事实层硬约束，而是：
  - 候选知识层的常驻注入
  - 过重的 NPC 档案块
  - 太泛、太虚的 continuity 块

后续建议工作流：

1. 先按本清单逐块确认是否改成条件注入
2. 再逐条审计 `runtime-rules.md` 与 `【要求】` 里的“删 / 改弱 / 保留”
3. 每次只动 1 到 2 个块，配合真实 session 体验回归，不做一口气大改
