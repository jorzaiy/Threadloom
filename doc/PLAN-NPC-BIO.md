# 实现计划：NPC Bio（轻量认知快照）

## 问题

narrator 无法拼出"NPC 是谁、经历了什么、知道什么"的完整画面。NPC 信息散落在 actor_registry、important_npcs、knowledge_records、event_summaries、persona_hooks 中，narrator 的 6 轮 recent window 无法覆盖 NPC 的历史经历。

典型案例：石根和主角一起在青石镇上车，但 narrator 写出"石根不知道青石镇在哪儿"。

## 方案

给活跃 NPC 维护一个 `bio` 字段——3-5 句话的当前有效认知快照，包含：
- 身份/来历（已确认的）
- 与主角的共同经历
- 当前状态和目标
- 关键知情范围（知道什么、不知道什么）

## 数据格式

在 `state.json` 的 `actors[actor_id]` 对象中新增字段：

```json
{
  "actor_id": "npc_003",
  "name": "石根",
  "bio": "十五岁少年，家贫，从青石镇关卡与陆小环结识。两人同乘板车从青石镇到黄岭，一起办了路牌（对外报陵阳城出发）。现跟随陆小环前往玄幽城，以雇佣同行为掩护。知道陆小环养灵貂、有竹签、替他付过钱；不知道她是筑基修士。",
  "bio_updated_turn": 208,
  ...
}
```

## 改动文件

### 1. `backend/state_keeper.py` — Keeper prompt 新增 `npc_bios` 字段

在 keeper prompt 的字段说明中新增：

```
- npc_bios（数组，最多3项）：本轮有重大变化的 NPC 认知快照更新。
  只在以下情况输出：NPC 首次出场、NPC 与主角发生重大共同事件、场景转换导致 NPC 状态变化。
  如果本轮无 NPC 重大变化，省略整个字段。
  格式：
  [
    {
      "actor_id": "npc_003",
      "bio": "3-5句话。包含：身份来历、与主角共同经历、当前状态目标、关键知情范围。必须是当前有效快照，不是流水账。"
    }
  ]
  规则：
  - bio 是覆盖式更新，新 bio 完全替换旧 bio
  - 必须包含 NPC 亲身经历的关键地点和事件（如一起上车、一起办事）
  - 必须标注 NPC 的知情边界（知道什么、不知道什么）
  - 主角对 NPC 说的谎话，NPC 的 bio 中应记为"被告知/听说"而非客观事实
```

### 2. `backend/state_keeper.py` — Merge 逻辑

在 `_merge_keeper_fill` 中提取 `npc_bios` 并暂存到 `merged['_pending_npc_bios']`（不直接写入 actors，因为 `normalize_state_dict` 会用 prev_actors 覆盖）。

### 3. `backend/handler_message.py` — 在 update_actor_registry 之后应用 bio

在 `update_actor_registry` 调用之后、`save_state` 之前，从 state 中取出 `_pending_npc_bios` 并写入对应 actor 的 `bio` 和 `bio_updated_turn` 字段。这样避免被 `normalize_state_dict` 的 actors merge 覆盖。

### 4. `backend/narrator_input.py` — 注入 narrator prompt

在现有的知情边界 block 中，每个 actor 的信息后追加 bio：

```
石根 [npc_003]：身份=十五岁少年，家贫；bio=十五岁少年，从青石镇关卡与陆小环结识...
```

只注入有 bio 的活跃 NPC（onstage + relevant），不注入 archived NPC。

### 5. `backend/actor_registry.py` — 无需改动

新建 actor 时不设 bio（正常），已有 actor 的 bio 字段不会被 `update_actor_registry` 清除（它只修改 name/aliases/relationship 等已知字段）。

## 审计发现

**`normalize_state_dict` 中的 actors merge 问题**：
`state_bridge.py:2151` 的 `current['actors'] = {**current_actors, **prev_actors}` 会用 prev 的整个 actor 对象覆盖 current。如果在 keeper merge 阶段写入 bio 到 actors 中，会被这行覆盖丢失。

**解决方案**：bio 写入时机放在 `normalize_state_dict` 之后（通过 `_pending_npc_bios` 暂存），在 handler_message.py 的主流程中应用。

## 触发条件

Keeper 不需要每轮输出 `npc_bios`。只在以下情况输出：
- NPC 首次出场（created_turn == current_turn）
- 场景转换（scene_shift == true）
- NPC 与主角发生重大共同事件（一起移动、一起完成任务、获知重要信息）

这由 keeper LLM 自行判断——prompt 中说明"如果本轮无 NPC 重大变化，省略整个字段"。

## Prompt 预算

- 每个 NPC bio: 200-400 字
- 活跃 NPC 5 个: 1-2K 字
- 注入位置：知情边界 block（当前 ~2400 字），增加后 ~3500 字
- 总 prompt 增量可控

## 测试策略

1. 单元测试：`npc_bios` 的 parse/merge/validate 逻辑
2. 回归测试：确保无 `npc_bios` 输出时行为不变
3. 在线验证：观察 e23032 session 后续轮次中 NPC bio 是否正确生成

## 风险

| 风险 | 缓解 |
|------|------|
| Keeper LLM 每轮都输出 bio（浪费 token） | prompt 明确"省略整个字段"；merge 时如果 bio 与旧值相同则不更新 |
| Bio 内容与事实矛盾 | bio 是覆盖式更新，错误会被下次更新修正；不影响 narrator 的 recent window 事实 |
| Bio 过长膨胀 prompt | 硬限 400 字/NPC，merge 时截断 |
| Actor_id 不匹配 | 验证 actor_id 存在于 actors 中，否则丢弃 |

## 实现顺序

1. state_keeper.py: prompt + merge（核心）
2. narrator_input.py: 注入（让 narrator 能看到 bio）
3. actor_registry.py: 保留字段（防止被清除）
4. 测试
