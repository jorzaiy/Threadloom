# Runtime Flow

**当前版本：v1.0**

## 一轮消息的最小流程

## 分层刷新策略

### 每轮轻刷新

每轮都读取：
- `runtime-rules`
- active preset
- 当前角色卡核心与世界约束字段
- `state`
- `scene persona seeds`
- 最近 `12` 对 recent history

这些不是同一优先级：`runtime-rules`、当前角色卡世界观、时代、题材、身份边界和世界机制是最高约束；recent history 与本轮用户输入只负责短期场景承接，不能反向改写角色卡世界。用户主角只是世界内角色，可以尝试行动和表达态度，但不能直接指定 NPC 服从、行动必然成功、关系成立、物品凭空出现或客观结论生效。

### 中等刷新（默认每 12 轮）

建议周期性重读：
- `relevant NPC profiles`
- `longterm persona seeds`
- 当前 relevant lore
- keeper archive

目的：
- 防止场景慢漂移
- 防止 relevant NPC / lore 选择长期失焦
- 用较早结构记录补足窗口外连续性

### 深刷新（默认每 20 轮或事件触发）

在以下情况做一次更完整的上下文重组：
- 场景主功能明显切换
- `Onstage NPCs` 明显换了一批
- 当前主事件改变
- 用户明确指出系统理解偏了

深刷新时可重新筛选：
- 当前 relevant NPC 档案
- 当前 relevant lore
- `scene/archive/longterm` persona 的前后台分布

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

当前默认 preset 是 `runtime-data/default-user/presets/world-sim-core.json`。

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
- 最近 `12` 对 turn 的 rolling window
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
- 当前 onstage / relevant NPC
- persona hooks
- relevant lore
- available cast / 可调入世界书人物
- correction rules
- 当前用户输入

`世界设定锁` 是 narrator prompt 的强约束块。它要求候选世界书、召回历史与用户输入先做整体语境兼容性判断；防污染不使用固定关键词黑名单，而是比较因果规则、时代感、社会制度、技术/超自然边界、人物身份与当前角色卡世界是否兼容。

同一个强约束块也负责用户控制权边界：用户输入不是世界命令，只是角色行动尝试。narrator 需要根据角色卡世界给出合理阻力、质疑、失败、延迟、代价、旁人反应或客观限制，而不是让用户一句话获得本应需要过程、证据、资源或权力才能得到的结果。

输出：
- `NarratorInput`

### Step 6. 调模型

生成 RP 正文。

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

输出：
- 新的 `state`
- 新的 `summary`
- 新的 `persona state`

### Step 8. 返回前端

返回：
- reply
- state snapshot
- 调试信息（可选）

---

## Backend Handler 顺序

`POST /api/message` 在 backend 内部建议按这个顺序执行：

1. 校验请求体
2. 解析 `session_id`，确认它属于当前角色卡作用域；若同名 session 存在于其他角色卡下，拒绝请求
3. 按解析后的 session 路径加锁
4. 检查 `(session_id, client_turn_id)` 是否已处理
5. 调 runtime `handle_turn(session_id, text, meta)`
6. runtime 返回 `reply + state_snapshot + debug`
7. backend 写访问日志 / 模型 usage
8. 返回 JSON 给前端

---

## 最小 Runtime Handler 伪代码

```python
def handle_turn(session_id: str, text: str, meta: dict) -> dict:
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

- `handle_turn()` 必须是 runtime 唯一主入口
- `runtime-rules.md` 必须在每次 `handle_turn()` 开始时优先加载
- 前端不要自己拼 prompt
- backend 不要自己判定剧情
- 模型调用层不要自己维护长期状态
- 所有写回必须发生在同一条 turn pipeline 中，避免状态分叉
- 刷新策略默认采用“每轮轻刷新 + 周期中刷新 + 事件触发深刷新”，不要只用死板的全量重读频率

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
