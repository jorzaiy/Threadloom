# Threadloom Architecture

**当前版本：v1.0**

## 目标

构建一个 `runtime-first` 的 RP 系统：

- HTML 前端负责输入输出
- backend 负责接入与会话壳子
- runtime 负责状态、人格、裁定、叙事
- 聊天历史不再是唯一真相源

## 当前目标态

当前 v1.0 目标不是“做成通用多租户平台”，而是把本地可用、角色卡可替换、可选多用户的 RP runtime 做成稳定主线。

当前已明确的产品边界：
- 默认单用户可用：不启用多用户时仍围绕 `default-user` 本地目录工作
- 可选多用户已进入产品面：管理员可启用多用户、创建用户、重置密码并管理用户开关
- 多角色卡当前支持枚举、导入、切换和删除，但仍偏“当前激活卡”工作流
- 单站点仍是 v1.0 产品层简化：站点连接全局唯一，管理员维护，普通用户只读；每个用户各自选择 `Narrator / State Keeper` 模型

当前不应误解为：
- 单站点是永久底层约束
- 多用户已可选启用，但不是公网 SaaS 多租户平台
- 角色卡系统只服务仓库内置卡

后续规划方向：
- 多用户：补忘记密码恢复、2FA/SSO 等平台化能力，而不是扩大当前本地多人模式的复杂度
- 多角色卡：继续打磨导入后的 runtime 清洗、资产管理与角色卡集合体验
- 多站点：若后续确实需要，再把单站点 UI 扩展为高级配置，而不是现在就把普通用户界面做复杂
- 角色卡导入：从“导入后手工修文件”推进到“稳定产出角色核心 / 世界书 / 开局 / 系统级 NPC / 资产”

结论：
- 当前阶段优先级是“稳定 runtime + 泛化角色卡 + 可选多用户隔离”
- 多站点与公网平台化属于后续高级能力，不是 v1.0 主目标

## 总体结构

```text
[ Browser / HTML Frontend ]
          │
          ▼
[ Thin Web Backend ]
          │
          ▼
[ RP Runtime Orchestrator ]
   ├─ canon / state / recent window / keeper archive
   ├─ npc profiles / persona seeds
   ├─ scene parsing
   ├─ arbiter
   ├─ narrator context build
   ├─ model call
   └─ writeback
```

## 分层职责

### Frontend

负责：
- 显示聊天记录
- 提交用户输入
- 显示当前状态面板
- 可选显示调试面板
- 桌面端把状态/调试面板作为右侧抽屉呈现，保持主阅读区纵向空间
- 移动端隐藏顶部 header，将 session、状态面板、设置入口收进输入区控制行，并把状态面板作为底部弹层
- 状态面板当前跟踪 `main_event / immediate_goal / carryover_signals / scene_entities / tracked_objects / possession_state / object_visibility`，不再把 `active_threads` 作为默认用户可见主面板项目

不负责：
- prompt 拼装
- state 判定
- persona 更新
- 裁定
- 角色卡导入后的结构清洗

### Backend

负责：
- 接收前端请求
- 管理 `session_id`
- 调用 runtime
- 返回 reply 与状态快照

不负责：
- 叙事决策
- 记忆真相维护
- 单独决定 persona 结论；persona 流转仍由 runtime 主链负责

### Runtime

负责：
- 启动时优先读取 `prompts/runtime-rules.md`
- 读取事实源
- 解析当前 turn
- 必要时裁定
- 生成 narrator 输入
- 调模型
- 写回 `history/state/summary/persona`

当前 narrator 主链说明：
- `summary` 当前仍保留为 session-local 写回 / 调试产物
- `summary` 当前不再作为 narrator 主输入
- narrator 当前主输入收敛为：
  - 最近 `12` 对 turn 的 rolling window
  - 命中的 keeper archive 结构记录

当前 keeper 写回质量边界：
- `skeleton keeper` 只维护 `time / location / main_event / onstage_npcs / immediate_goal` 最小骨架。
- `fill keeper` 只输出本轮增量 patch，主要补 `carryover_signals / tracked_objects / possession_state / object_visibility / knowledge_scope`。
- `knowledge_scope` 是本轮新增知情 delta，不是长期知识库；长期知识只写入 actor-id 版 `knowledge_records`，并做轻量相似去重。
- object patch 不应携带 baseline 全量对象；物件消耗、摧毁、遗失或归档通过 `lifecycle_status` 表达，并进入 `graveyard_objects`。
- `keeper_record_archive.json` 是派生缓存；刷新前会 prune 超过当前有效 pair count 的未来 records，避免 undo / regenerate 后召回坏档。

当前已落地的 persona 责任：
- 维护 session-local `scene/archive/longterm` persona 层
- 用保守门槛控制哪些 NPC 值得拥有运行时人格骨架
- 优先把“持续互动 / 世界书重要人物 / 线索承载者”纳入 persona，而不是给一次性 NPC 普遍建档
- 在场景切换后，把不再互动的人物逐步降到 `archive`
- 优先消费导入器产出的 `system-npcs.json`，而不是主要依赖世界书关键词临时猜系统角色
- persona root seed 只来自当前角色卡 source；缺失时不再读取仓库共享 `runtime/persona-seeds`，避免不同角色卡的人格骨架静默继承

## Session / 角色卡隔离

当前运行时以 `runtime-data/<user>/characters/<character_id>/sessions/<session_id>/` 作为 session-local 真相源。每个 session 的 `context.json` 会记录创建时的 `user_id / character_id / session_root / session_dir`，HTTP 入口在访问 state、history、message、regenerate、delete 前会检查当前角色卡下是否拥有该 session。

如果同名 session 存在于其他角色卡目录下，后端会拒绝当前请求，而不是在当前角色卡下静默 bootstrap 一个同名 session 或把旧历史配上新角色卡上下文。单用户旧版 `/sessions` 目录仍作为兼容 fallback 存在，但多用户 request context 会禁用 legacy fallback。

隔离补充规则：
- history cache 使用实际 `history.jsonl` 路径作为 key，而不是裸 `session_id`
- 角色卡导入 / 聊天导入的临时角色卡 override 是 request-local，不跨线程共享
- 角色卡 source 资产导入的临时 root override 是 request-local，不跨并发导入共享

## 角色卡 source 结构

当前角色卡 source 目录建议形态：

- `character-data.json`
- `player-profile.override.json`（可选）
- `lorebook.json`
- `openings.json`
- `system-npcs.json`
- `import-manifest.json`
- `assets/`
- `memory/`
- `runtime/persona-seeds/`

其中：

- `character-data.json` 是角色核心；其中 `displaySummary` 是供角色卡管理 UI 使用的短简介，不参与替代运行时世界书
- `player-profile.override.json` 是当前角色卡对主角档案的特化覆盖
- `lorebook.json` 是世界知识
  - 导入器会把 Tavern 外层条目中嵌套的 JSON-like `entries[]` 展开成多条运行时世界书
  - `enabled: false` / `disable: true` / 初始引导 / 状态栏 / 人际模板等非运行时知识会被过滤
- `openings.json` 是开局菜单与 bootstrap
- `system-npcs.json` 是系统级既有人物
- 当前 `system-npcs.json` 建议分层：
  - `core`
  - `faction_named`
  - `roster`
- `assets/` 是封面等静态资产

这比旧的“把各种 hints、开局、系统规则、前端残余字段一起塞进 character-data.json”更稳，也更容易泛化到不同角色卡。

## 主角档案分层

当前 RP 主角档案建议分两层：

- 用户级基础档案：`runtime-data/<user>/profile/player-profile.base.json`
- 角色卡特化覆盖：`runtime-data/<user>/characters/<character_id>/source/player-profile.override.json`

运行时会先读取基础档案，再叠加当前角色卡覆盖，形成当前 narrator / state 主链消费的主角档案。

补充说明：

- `USER.md` 不再作为 RP narrator 主链输入
- narrator 运行时只消费一份收短后的玩家档案摘要，避免完整人物设定每轮过度挤占上下文
- `player-profile.json` / `player-profile.md` 当前主要作为兼容副本与可读导出

### Runtime 启动顺序

`runtime-first` 版本的启动顺序应固定为：

1. `prompts/runtime-rules.md`
2. `character/character-data.json`
3. active preset
4. `character/lorebook.json`
5. `memory/canon.md`
6. `memory/state.md`
7. relevant `memory/npcs/*.md`
8. relevant `runtime/persona-seeds/*`
9. 最近 `12` 对 recent history
10. keeper archive recall 命中

原则：
- `runtime-rules.md` 必须先于其他上下文被加载
- 它是 runtime 的长期底板，不依赖未注入的会话惯性；但每轮必须服从已注入的本轮输入与最近上下文

## 真相源顺序

第一真相源：
- 本轮用户输入
- 最近 12 对完整 recent window
- `runtime-rules` 中的主角控制权、知情边界与世界运行原则

辅助真相源：
- `actors / items / knowledge` 长期账本
- 固定分段 summary chunk（只补 recent window 外历史）
- 世界书 foundation / 情境条目（只补世界规则、势力背景与解释）
- `state` / `event` / `thread`（state/debug/recall 辅助，不默认主导 narrator 当前事实）

## Narrator Prompt 分层

当前 narrator prompt 采用分层权重，而不是简单删块：

强约束层：
- 玩家档案（runtime slim 版）
- 知情边界
- 最近窗口

连续性层：
- actor registry（长期基础设定，不表示当前在场）
- 重要物件与持有关系
- 情报账本
- 召回的固定 summary chunk

写回边界：
- `knowledge_scope` 只代表本轮新增知情，不作为长期连续性层直接累积；长期连续性消费 `knowledge_records`。
- `tracked_objects` 只保留 active 物件；`consumed / destroyed / lost / archived` 物件进入 `graveyard_objects`。
- `possession_state` 与 `object_visibility` 允许本轮合法新状态覆盖旧状态，但非法 holder 或非法 object id 不覆盖旧正常数据。

候选知识层：
- 系统级 NPC
- 可调入世界书 NPC
- 世界书正文

当前运行原则：
- 本轮用户输入与最近 12 对完整上下文是当前场景事实源。
- 连续性层只用于保持长期设定、物件归属、知情边界和 recent window 外历史，不可回滚 recent window 中已经发生的空间关系、控制权或行动链变化。
- 候选知识层只表示“可调用”，不表示“此刻已在场”或“当前已发生”。
- prompt 中避免为具体剧情动作维护关键词式规则；连续性要求用通用的空间关系、视线范围、人物控制权与行动链原则表达。
- narrator 的目标不是围着主角单点响应，而是维持一个会自己流转的 RP 世界：主角是参与者与观察者，不是唯一驱动器。

当前已开始把部分候选知识块改成规则版条件注入：
- 世界书正文：只有在当前场景明显需要世界规则/势力/地点解释时才注入
- 系统级 NPC / 世界书 NPC 候选：只作为候选知识层，必须通过场景内可感知路径自然接入
- 相关 NPC 档案：已让位于 actor registry；短期状态不写入长期人物基础设定

当前 selector 已从 `context_builder.py` 中抽离为独立模块：
- `backend/selector.py`
- 职责：在 narrator 开写前决定这一轮是否值得补 `lorebook_text / system_npc_candidates / lorebook_npc_candidates / npc_profiles`

当前 keeper 前也已接入一层最小 `event_ledger`：
- `backend/event_ledger.py`
- 职责：先从本轮 narrator 回复里筛出更像“局势句”的候选，再交给 keeper 写 `main_event`
- 当前不承担 NPC 过滤职责，边界仍与 NPC pipeline 分离

## Event / Signal / Summary / Thread Draft

当前建议把这四层分开看，而不是都当成“连续性结构”：

- `signal`
  - 面向当前 narrator / selector
  - 表示：当前仍未消失、接下来几拍仍会影响局势推进的 `risk / clue / mixed` 信号
  - 更新频率：高频，尽量每轮都能维护

- `event`
  - 面向 recall / summary
  - 表示：最近 3 回合左右到底发生了什么值得检索的事件片段
  - 默认不直送 narrator；只有 selector 判断 recent window 不足以恢复背景时才回流

- `summary`
  - 面向长程压缩
  - 表示：更长阶段的压缩结果
  - 默认不常驻 narrator，只在旧事件确实回流时条件注入

- `thread`
  - 面向 state/debug 观察
  - 表示：keeper 当前如何把局势拆成主线/风险/线索的运行时辅助结构
  - 当前实验方向是不再让它主导 narrator 或 selector

这个草案的核心原则是：
- narrator 负责真正推进
- event 负责检索
- signal 负责当前方向约束
- summary 负责长程压缩
- thread 若保留，也尽量不要再承担 steering 职责

当前 preset 已重新定位为“节奏 / 镜头 / 注入预算调制器”，而不是世界真相或事实边界的主来源：
- 默认 preset 名称由 `config/runtime.json -> sources.active_preset` 指定；当前主配置为 `world-sim-core`
- preset 文件通过 `backend/paths.py` 的分层路径解析加载，不再承诺固定用户目录路径
- 主角控制权、知情边界、世界自主流转等长期规则，应放在 `runtime-rules.md`

不应成为主真相源：
- 超长聊天 transcript

## 前端页面最小布局

### 左侧：聊天区
- assistant 消息
- user 消息
- 输入框
- 发送按钮

### 状态区
- 当前时间
- 当前地点
- 当前主事件
- Onstage NPCs
- Relevant NPCs
- Immediate Goal
- Immediate Risks

说明：
- 当前状态区已改为浮动面板，不再是常驻右侧栏。
- `Onstage NPCs` / `Relevant NPCs` 中的每个名字都应可点击。
- 点击后打开一个只读详情面板，展示对应 `scene entity` 的当前数据。
- 第一版不提供任何人工编辑按钮。

### 折叠调试区
- Scene Entities
- Carryover Clues
- 当前 persona seeds
- 当前 preset
- 最近一次裁定结果

## NPC 详情查看

前端应以 `entity_id` 作为查看入口，而不是以显示名作为唯一键。

原因：
- 同一个 NPC 可能有多个称呼
- 同一个称呼也可能在不同场景指向不同人物

因此：
- 前端列表显示 `primary_label`
- 点击时请求 `GET /api/entity?session_id=...&entity_id=...`
- 详情面板里展示：
  - `primary_label`
  - `aliases`
  - `role_label`
  - `onstage/relevant`
  - `possible_links`
  - persona seed
  - debug reasons

这块默认只读。
若有误判，优先通过 runtime / runner 自动修正，而不是由用户直接改写数据。

## 第一版边界

第一版先做：
- HTML 前端
- 最小 backend
- runtime 主链
- 直接调用模型 API
- 最小 persona 流转
- 可调入世界书人物注入

第一版暂不做：
- 多渠道
- 完整多用户产品
- 多故事并行
- 复杂权限系统
- 设备节点
- 高精度 arbiter
- 完整的 world simulation 调度层

## OpenClaw 的位置

如果后续要复用 OpenClaw，建议只复用：
- 模型调用封装
- 工具能力
- 渠道适配

不要复用为：
- 主会话引擎
- 主上下文管理器
- 主叙事编排器
