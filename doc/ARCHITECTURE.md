# Threadloom Architecture

## 目标

构建一个 `runtime-first` 的 RP 系统：

- HTML 前端负责输入输出
- backend 负责接入与会话壳子
- runtime 负责状态、人格、裁定、叙事
- 聊天历史不再是唯一真相源

## 总体结构

```text
[ Browser / HTML Frontend ]
          │
          ▼
[ Thin Web Backend ]
          │
          ▼
[ RP Runtime Orchestrator ]
   ├─ canon / state / summary
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

不负责：
- prompt 拼装
- state 判定
- persona 更新
- 裁定

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

当前已落地的 persona 责任：
- 维护 session-local `scene/archive/longterm` persona 层
- 用保守门槛控制哪些 NPC 值得拥有运行时人格骨架
- 优先把“持续互动 / 世界书重要人物 / 线索承载者”纳入 persona，而不是给一次性 NPC 普遍建档
- 在场景切换后，把不再互动的人物逐步降到 `archive`

### Runtime 启动顺序

`runtime-first` 版本的启动顺序应固定为：

1. `prompts/runtime-rules.md`
2. `character/character-data.json`
3. active preset
4. `character/lorebook.json`
5. `memory/canon.md`
6. `memory/state.md`
7. `memory/summary.md`
8. relevant `memory/npcs/*.md`
9. relevant `runtime/persona-seeds/*`
10. 少量 recent history

原则：
- `runtime-rules.md` 必须先于其他上下文被加载
- 它是 runtime 的长期底板，不应被当前在线会话历史压过

## 真相源顺序

第一真相源：
- `runtime-rules`
- `canon`
- `state`
- `summary`
- `npc profiles`
- session-local `persona seeds`

辅助真相源：
- 少量 recent history
- 可调入世界书人物

不应成为主真相源：
- 超长聊天 transcript

## 前端页面最小布局

### 左侧：聊天区
- assistant 消息
- user 消息
- 输入框
- 发送按钮

### 右侧：状态区
- 当前时间
- 当前地点
- 当前主事件
- Onstage NPCs
- Relevant NPCs
- Immediate Goal
- Immediate Risks

说明：
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
- 多用户
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
