# Threadloom API

## 概览

当前已实现的接口：
- `GET /`
- `GET /api/health`
- `GET /api/sessions`
- `GET /api/state?session_id=...`
- `GET /api/history?session_id=...`
- `GET /api/entity?session_id=...&entity_id=...`
- `POST /api/message`
- `POST /api/new-game`
- `POST /api/delete-session`
- `POST /api/regenerate-last`

当前未实现但文档中偶尔会提到的接口：
- `POST /api/admin/adjust`

## GET /api/health

用于确认 backend 是否已监听。

### Response

```json
{
  "ok": true,
  "service": "threadloom-backend",
  "host": "127.0.0.1",
  "port": 8765
}
```

## POST /api/message

用户发送消息的主入口。

### Request

```json
{
  "session_id": "story-live",
  "text": "用户输入",
  "client_turn_id": "web-1710000000000",
  "meta": {
    "source": "web",
    "debug": true
  }
}
```

### Request Rules

- `session_id` 必填
- `text` 必填，trim 后不能为空
- `client_turn_id` 可选，但前端应尽量总是传
- `meta.debug=true` 时才返回 `debug`

### Current Behavior

当前实现不是单纯 narrator 直出，而是：
- 先确保 session bootstrap 完成
- opening 菜单态优先处理
- 组装 runtime context
- 运行最小 arbiter
- 调 narrator 模型
- 完整回复才继续写回 `state / summary / persona / threads / important_npcs`

当前 state 写回还有两层额外约束：
- `state_keeper` 会拒收低信号 JSON，并对照上一轮 state 检查是否出现异常回退
- fallback `state_updater` 会优先保留已有高信号字段，而不是轻易用弱推断覆盖

opening 相关行为：
- 新档首轮输入 `开始游戏` / `开始` / `重新开始` 会进入 opening 菜单
- 若输入数字、开局标题或 `随机开局`，会直接解析开局并进入开局正文
- 若已进入开局，再次输入开局命令会返回 guard 提示，不推进主链
- opening 菜单阶段如果输入无效选项，会回显开局菜单或提示继续选择，不进入正常 runtime 主链

partial 相关行为：
- 若 narrator 返回 `finish_reason=length`，该 assistant 回复会标记为 `partial`
- partial 回复会保留在历史里显示
- 但不会继续污染 `state / summary / threads / important_npcs`

### Success Response

```json
{
  "session_id": "story-live",
  "turn_id": "turn-0042",
  "reply": "assistant 正文",
  "usage": {
    "model": "gpt-5.4",
    "input_tokens": 1234,
    "output_tokens": 567,
    "finish_reason": "stop"
  },
  "state_snapshot": {
    "time": "承和十二年，三月初七，入夜",
    "location": "密林与树下藏身处一带",
    "main_event": "安顿、休整并决定下一步去向。",
    "scene_core": "伤势与风险压着场面、场面暂时转入安顿与恢复。",
    "scene_entities": [
      {
        "entity_id": "scene_npc_01",
        "primary_label": "师兄",
        "aliases": ["师兄"],
        "role_label": "同行伤者 / 师兄",
        "onstage": true,
        "possible_link": null
      }
    ],
    "onstage_entities": [
      {
        "name": "师兄",
        "entity_id": "scene_npc_01",
        "role_label": "同行伤者 / 师兄",
        "ambiguous": false
      }
    ],
    "relevant_entities": [],
    "active_threads": [],
    "important_npcs": [],
    "onstage_npcs": ["师兄", "皂衣人"],
    "relevant_npcs": ["少年"],
    "immediate_goal": "先安顿与恢复，再决定下一步行动。",
    "immediate_risks": ["外部追索仍可能回到前台。"],
    "carryover_clues": ["前一场景留下的环境后果仍可能存在。"]
  },
  "debug": {
    "scene_mode": "runtime-loaded",
    "arbiter_used": true,
    "arbiter_event_count": 1,
    "arbiter_analysis": {},
    "arbiter_results": [],
    "active_persona": ["师兄"],
    "loaded_preset": "world-sim-balanced",
    "loaded_onstage": ["师兄", "皂衣人"],
    "state_keeper_diagnostics": {},
    "retained_threads": [],
    "retained_entities": []
  }
}
```

### Notes

- `reply` 只包含用户可见正文
- `state_snapshot` 是前端右侧状态栏可直接消费的精简快照
- `turn_id` 由 backend 生成
- 当前后端对同一 `session_id` 已做串行化处理，避免同一会话并发请求互相覆盖
- 幂等缓存键是 `(session_id, client_turn_id)`
- 当前 GET/POST 响应会附带 `web` 配置块，用于驱动前端 `default_debug / show_debug_panel / history_page_size`

### Error Response

```json
{
  "error": {
    "code": "INVALID_INPUT",
    "message": "text is required"
  }
}
```

当前常见错误码：
- `INVALID_INPUT`
- `NOT_FOUND`
- `ENTITY_NOT_FOUND`
- `NO_PARTIAL_TURN`
- `INTERNAL_ERROR`

## GET /api/state

返回当前会话的精简状态面板。

### Query

- `session_id` 必填

### Response

```json
{
  "session_id": "story-live",
  "state": {
    "time": "...",
    "location": "...",
    "main_event": "...",
    "scene_core": "...",
    "scene_entities": [],
    "onstage_entities": [],
    "relevant_entities": [],
    "active_threads": [],
    "important_npcs": [],
    "onstage_npcs": ["..."],
    "relevant_npcs": ["..."],
    "immediate_goal": "...",
    "immediate_risks": ["..."],
    "carryover_clues": ["..."]
  }
}
```

### Notes

- `onstage_entities` / `relevant_entities` 是前端推荐使用的实体展示结构
- 前端不应再自行用名字反查 `entity_id`

## GET /api/history

返回当前会话最近消息。

### Query

- `session_id` 必填

### Response

```json
{
  "session_id": "story-live",
  "messages": [
    {
      "ts": 1710000000000,
      "role": "user",
      "content": "..."
    },
    {
      "ts": 1710000000100,
      "role": "assistant",
      "content": "...",
      "completion_status": "complete"
    }
  ]
}
```

### Notes

- 当前实现最多返回最近 80 条消息
- 实际分页大小由 `runtime.json -> web.history_page_size` 控制
- partial assistant 也会在这里返回，但不会进入事实层写回

## GET /api/entity

返回单个 scene entity 的详情。

### Query

- `session_id` 必填
- `entity_id` 必填

### Response

```json
{
  "session_id": "story-live",
  "entity": {
    "entity_id": "scene_npc_01",
    "primary_label": "师兄",
    "aliases": ["师兄"],
    "role_label": "同行伤者 / 师兄",
    "onstage": true,
    "relevant": true,
    "possible_links": [],
    "runtime_state": {},
    "persona": {},
    "debug": {}
  }
}
```

### Notes

- 当前会优先显示 session-local persona
- 若 session 内没有对应 persona，才 fallback 到 root persona 或派生骨架

## GET /api/sessions

返回当前角色卡下可切换的 session 列表。

### Response

```json
{
  "sessions": [
    {
      "session_id": "story-live-20260406-203000",
      "archived": false,
      "replay": false,
      "active_preset": "world-sim-balanced",
      "bootstrapped_main_event": "开局：雨夜逢杀。"
    }
  ]
}
```

## POST /api/new-game

归档当前 session，并新建一个新的 session。

### Request

```json
{
  "session_id": "story-live"
}
```

### Response

```json
{
  "session_id": "story-live-20260407-120000",
  "previous_session_id": "story-live",
  "archived_to": "sessions/archive-20260407-120000-story-live",
  "reply": "这是碎影江湖。雾未散，刀已出鞘。你要从哪一步踏入这片江湖？",
  "state_snapshot": {
    "time": "待确认",
    "location": "待确认",
    "main_event": "开局待展开。"
  },
  "messages": [
    {
      "ts": 1710000000000,
      "role": "assistant",
      "content": "...开局文案..."
    }
  ]
}
```

### Notes

- 新会话不是清空 root `memory/*`，只是创建新的 session-local 档案
- 新会话默认直接进入 opening 状态机

## POST /api/delete-session

删除当前 session，并删除与其连接的 archive lineage。

### Request

```json
{
  "session_id": "story-live-20260407-120000"
}
```

### Response

```json
{
  "session_id": "story-live-20260407-120000",
  "deleted": true,
  "deleted_paths": [
    "sessions/story-live-20260407-120000"
  ],
  "sessions": []
}
```

## POST /api/regenerate-last

仅当“最后一条 assistant 回复为 partial”时可用。

### Request

```json
{
  "session_id": "story-live"
}
```

### Current Behavior

当前实现会：
- 检查最后两条历史是否为 `user -> assistant(partial)`
- 回滚最后一对 user/assistant
- 回退 `last_turn_id`
- 按 `turn_id` 清理对应幂等缓存项
- 重新调用 `handle_message()` 生成该轮

### Error

```json
{
  "error": {
    "code": "NO_PARTIAL_TURN",
    "message": "latest assistant reply is not partial"
  }
}
```
