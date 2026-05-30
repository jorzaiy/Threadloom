# Threadloom API

**当前版本：v1.0**

## 概览

当前已实现的接口：
- `GET /`
- `GET /api/health`
- `GET /api/site-config`
- `POST /api/site-config`
- `POST /api/site-models/discover`
- `GET /api/providers`
- `POST /api/providers`
- `POST /api/providers/discover`
- `DELETE /api/providers`
- `GET /api/model-config`
- `POST /api/model-config`
- `GET /api/narrator-preset`
- `POST /api/narrator-preset`
- `GET /api/sessions`
- `GET /api/state?session_id=...`
- `GET /api/history?session_id=...`
- `GET /api/entity?session_id=...&entity_id=...`
- `POST /api/message`
- `POST /api/new-game`
- `POST /api/delete-session`
- `POST /api/regenerate-last`
- `POST /api/delete-latest-turn`
- `GET /api/characters`
- `POST /api/character/select`
- `POST /api/character/delete`
- `POST /api/character/rebuild-lorebook`
- `GET /api/user-profile`
- `POST /api/user-profile`
- `POST /api/user-profile/normalize`
- `POST /api/user-profile/preview`
- `GET /api/character/profile-override`
- `POST /api/character/profile-override`
- `POST /api/character/profile-override/normalize`
- `POST /api/character/profile-override/preview`
- `POST /api/characters/profile-override`（兼容别名）
- `POST /api/user-avatar`
- `POST /api/user-avatar/delete`
- `GET /user-avatar`
- `GET /character-cover`
- `POST /api/characters/import`
- `POST /api/chat/preview`
- `POST /api/chat/import`

当前未实现但文档中偶尔会提到的接口：
- `POST /api/admin/adjust`

当前多用户接口：默认单用户模式下不强制登录；管理员启用多用户后进入正式认证/用户管理流程。
- `GET /api/auth/me`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/change-password`
- `GET/POST /api/users`
- `POST /api/multi-user`

## Multi-user API notes

- 多用户关闭时，业务接口默认解析为 `default-user`，不强制登录。
- 多用户开启后，除公开路径外都需要有效 token；POST/DELETE/PUT 等 state-changing 请求只接受 `Authorization: Bearer <token>`，不接受 Cookie token。
- 多用户开启且未认证时，`GET /` 与 `GET /index.html` 只返回最小登录页；不会返回完整 SPA DOM。`GET /app.js` 同样需要有效 token，避免未登录用户枚举完整前端应用逻辑。登录页需要的 `/login.js`、`/styles.css`、`/favicon.svg` 仍保持公开。
- `POST /api/auth/login` 受后端进程内 per-IP 与全局窗口限速；超过窗口返回 `429 RATE_LIMITED`。
- token TTL 为 30 天，只对仍存在且未禁用的账号有效；主动登出、管理员禁用或归档删除账号后，残留 token 会被拒绝。
- `GET /api/auth/me` 在已登录状态会回写 `Set-Cookie: session_token=<token>` 以便 `<img>` 等无法发 Bearer 的 GET 端点继续认证；该回写仅在 token 仅由 `[A-Za-z0-9_-]` 组成且长度 ≤ 256 时进行（`secrets.token_urlsafe` 的字符集），防止恶意 Authorization 头注入额外响应头。

### GET /api/users

管理员专用。返回当前账号列表、多用户开关状态，以及用户数据目录审计信息。

```json
{
  "users": [
    {
      "user_id": "default-user",
      "role": "admin",
      "created_at": 1710000000,
      "has_password": true,
      "disabled": false,
      "disabled_at": 0
    }
  ],
  "storage": {
    "orphan_dirs": [],
    "missing_dirs": [],
    "deleted_archives": []
  },
  "multi_user_enabled": true
}
```

`storage.orphan_dirs` 表示存在于 `runtime-data/`、但不在 `_system/users.json` 中注册的用户形态目录；接口不会自动删除或恢复，管理员可用 `archive_orphan_dir` 手动归档。

### POST /api/users

管理员专用；首次单用户 bootstrap 设置管理员密码仍走既有例外路径。

支持的 `action`：

- `create`：创建普通用户，字段：`user_id`、`password`
- `reset_password`：重置普通用户密码，字段：`user_id`、`password`
- `set_admin_password`：设置或更新 `default-user` 管理员密码，字段：`password`
- `disable`：禁用普通用户并撤销其全部 token，字段：`user_id`，可选 `reason`
- `enable`：重新启用普通用户，字段：`user_id`
- `delete`：归档删除普通用户，字段：`user_id`
- `archive_orphan_dir`：归档删除未注册的孤儿用户目录，字段：`user_id`

`delete` 会先把 `runtime-data/<user>/` 移动到 `runtime-data/_system/deleted-users/<user>-<timestamp>`，成功后才删除账号记录和 sessions；如果移动失败，账号和 token 保持原状。

`archive_orphan_dir` 只接受不在账号注册表中的孤儿目录，会移动到 `runtime-data/_system/deleted-users/<user>-orphan-<timestamp>`；已注册用户和 `default-user` 会被拒绝。

### POST /api/multi-user

管理员专用。启用或关闭多用户模式，并清空所有 sessions。请求必须包含管理员密码，后端会在切换前重新验证。

```json
{
  "enabled": true,
  "password": "admin-password"
}
```

## GET /api/site-config

返回全局单站点配置快照，以及已获取的模型列表。多用户开启后，站点连接由管理员（`default-user`）统一维护，普通用户只读且不会看到完整 API Key。

## POST /api/site-config

管理员专用。更新全局站点 URL / API Key / API 类型；普通用户在多用户模式下会收到 `FORBIDDEN`。

## POST /api/site-models/discover

管理员专用。向当前站点请求 `/models`，并刷新全局可选模型列表。

## GET /api/model-config

返回当前用户的 `Narrator / State Keeper` 模型选择。

## POST /api/model-config

更新当前用户的 `Narrator / State Keeper` 模型选择。

## GET /api/narrator-preset

读取指定 narrator preset。Query：

- `preset_id` 必填

## POST /api/narrator-preset

保存或删除当前用户的 narrator preset。

保存请求体：

```json
{
  "preset_id": "world-sim-core",
  "content": {}
}
```

删除请求体：

```json
{
  "preset_id": "old-preset",
  "delete": true
}
```

### POST /api/auth/change-password

已登录用户自助修改密码。请求必须带 Bearer token。

```json
{
  "old_password": "current-password",
  "new_password": "new-password-at-least-12-chars"
}
```

### Notes

- `temperature` 与 `max_output_tokens` 当前不再由普通用户在前端设置
- 这两个参数统一来自 `config/runtime.json -> model_defaults`

## Player profile API

玩家设定采用“自然语言源文本 + 统一 JSON + prompt 预览”的三层结构。前端默认让用户编辑自然语言，调用 State Keeper 模型整理成固定 JSON；高级用户可直接编辑 JSON 的字段值和数组项，但不能改 schema 结构。

统一 JSON schema：

```json
{
  "schemaVersion": 1,
  "identity": {
    "name": "",
    "courtesyName": "",
    "gender": "",
    "age": "",
    "origin": "",
    "status": ""
  },
  "appearance": [],
  "abilities": [],
  "personality": [],
  "preferences": [],
  "background": [],
  "psychology": [],
  "worldAdaptation": [],
  "privateBoundaries": []
}
```

规则：

- `identity` 只能包含上述 6 个字符串字段。
- 其他字段必须是字符串数组；用户可以增删数组项，但不能把数组改成对象或字符串。
- 后端会拒绝未知顶层字段、未知 identity 字段和错误类型；校验失败不会覆盖旧档案。
- 旧版嵌套 profile 会在读取 API 中转换为统一格式，runtime prompt 只消费统一 JSON 渲染后的 `【玩家档案】`。

### GET /api/user-profile

返回用户级基础档案、自然语言源文本和最终注入预览。

```json
{
  "profile": {"schemaVersion": 1, "identity": {"name": "陆小环"}},
  "source_text": "自然语言设定原文",
  "prompt_preview": "# 玩家档案\n...",
  "avatar_url": "/user-avatar"
}
```

### POST /api/user-profile

保存用户级基础档案。请求体：

```json
{
  "profile": {"schemaVersion": 1, "identity": {"name": "陆小环"}},
  "source_text": "自然语言设定原文"
}
```

### POST /api/user-profile/normalize

用 State Keeper 模型把自然语言整理成统一 JSON。不会自动保存，前端应展示 JSON 和 prompt preview 给用户确认。

```json
{
  "source_text": "陆小环，女，散修，灵识敏锐……",
  "profile": {"schemaVersion": 1, "identity": {}}
}
```

返回：

```json
{
  "profile": {"schemaVersion": 1, "identity": {"name": "陆小环"}},
  "prompt_preview": "# 玩家档案\n...",
  "diagnostics": {"provider_used": "llm"}
}
```

### POST /api/user-profile/preview

校验传入 JSON 并返回最终 `【玩家档案】` 预览，不保存。

当前角色卡专属覆盖使用同一 schema：

- `GET /api/character/profile-override`
- `POST /api/character/profile-override`
- `POST /api/character/profile-override/normalize`
- `POST /api/character/profile-override/preview`

字段名分别使用 `override` 替代 `profile`。兼容别名 `POST /api/characters/profile-override` 仍可保存当前角色卡覆盖。

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
- narrator 主模型最多重试 3 次；全部失败后使用 State Keeper 模型作为副 LLM 最多再重试 3 次
- 完整回复才继续写回 `state / summary / persona / threads / important_npcs`

当前 state 写回还有两层额外约束：
- `state_keeper` 会拒收低信号 JSON，并对照上一轮 state 检查是否出现异常回退
- runtime fallback 会先用 `state_fragment.build_state_from_fragment()` 形成 `fragment-baseline`，优先保留已有高信号字段；`state_updater.py` 当前主要用于离线 replay / rebuild 工具链

opening 相关行为：
- 新档首轮输入 `开始游戏` / `开始` / `重新开始` 会进入 opening 菜单
- 若输入数字、开局标题或 `随机开局`，会直接解析开局并进入开局正文
- 若已进入开局，再次输入开局命令会返回 guard 提示，不推进主链
- opening 菜单阶段如果输入无效选项，会回显开局菜单或提示继续选择，不进入正常 runtime 主链

partial 相关行为：
- 若 narrator 返回 `finish_reason=length`，该 assistant 回复会标记为 `partial`
- 若 narrator 返回的正文明显停在半句中间，即使 provider 没给 `finish_reason`，当前也会按 `partial` 处理
- partial 回复不会作为已提交正文保留在历史或事实层；生成阶段会自动重试，重试耗尽后返回空 `reply` 与 `NARRATOR_INCOMPLETE`
- 旧历史中的 partial assistant 会在 `/api/history` 和 prompt recent window 中连同对应 user 输入一起过滤
- 若主/副 narrator 全部失败，返回空 `reply` 与 `NARRATOR_UNAVAILABLE`，本轮不写历史、不递增 turn、不更新 state；详情见响应里的 `narrator_retry`

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
    "actors": {
      "npc_001": {
        "kind": "npc",
        "name": "严教官",
        "relationship_to_protagonist": {
          "label": "队友",
          "evidence": "并肩完成夜巡",
          "updated_turn": 7
        }
      }
    },
    "actor_context_index": {},
    "onstage_npcs": ["师兄", "皂衣人"],
    "relevant_npcs": ["少年"],
    "scene_objective": {
      "label": "林中休整",
      "objective": "让主角完成短暂补给并决定下一步路线",
      "status": "active"
    },
    "immediate_goal": "先安顿与恢复，再决定下一步行动。",
    "carryover_signals": [
      {"type": "clue", "text": "林外仍有追索痕迹"}
    ],
    "immediate_risks": ["外部追索仍可能回到前台。"],
    "carryover_clues": ["前一场景留下的环境后果仍可能存在。"],
    "tracked_objects": [
      {
        "object_id": "obj_01",
        "label": "油纸包饼",
        "kind": "item",
        "story_relevant": true
      }
    ],
    "possession_state": [
      {"object_id": "obj_01", "holder": "主角", "status": "saved", "location": "怀里"}
    ],
    "object_visibility": [
      {"object_id": "obj_01", "visibility": "private", "known_to": ["主角"]}
    ],
    "graveyard_objects": []
  },
  "debug": {
    "scene_mode": "runtime-loaded",
    "arbiter_used": true,
    "arbiter_event_count": 1,
    "arbiter_analysis": {},
    "arbiter_results": [],
    "active_persona": ["师兄"],
    "loaded_preset": "world-sim-core",
    "loaded_onstage": ["师兄", "皂衣人"],
    "prompt_block_stats": [],
    "event_summary_count": 12,
    "selector": {
      "event_hits": [],
      "summary_chunk_hits": [],
      "inject_summary": false
    },
    "event_summary_item": {},
    "lorebook_injection": {
      "selected_summary_chars": 0,
      "source_hit_chars": 0,
      "index_hit_chars": 0,
      "foundation_chars": 0,
      "effective_total_chars": 0
    },
    "state_keeper_diagnostics": {},
    "retained_threads": [],
    "retained_entities": []
  }
}
```

### Notes

- `reply` 只包含用户可见正文
- `state_snapshot` 是前端右侧状态栏可直接消费的精简快照
- `scene_objective` 是当前事件/场景段目标；`immediate_goal` 是主角下一拍目标，二者不要混用
- `carryover_signals` 是当前统一信号层，旧 `immediate_risks / carryover_clues` 仍为兼容展示字段
- `actors.*.relationship_to_protagonist` 是 Keeper 从 narrator 正文证据沉淀出的 NPC 与主角关系标签；它只绑定到既有 NPC actor，不代表玩家可以在输入中直接指定关系成立
- 调试面板中的 selector / prompt / lorebook 统计用于解释“本轮为什么注入这些上下文”，不是事实编辑入口
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
- `SESSION_NOT_FOUND`
- `NO_PARTIAL_TURN`
- `NO_REGENERATABLE_TURN`
- `TURN_TRACE_MISSING`
- `NARRATOR_UNAVAILABLE`
- `NARRATOR_INCOMPLETE`
- `AUTH_REQUIRED`
- `AUTH_FAILED`
- `RATE_LIMITED`
- `FORBIDDEN`
- `SESSION_CHARACTER_MISMATCH`
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
    "scene_entities": [],
    "onstage_entities": [],
    "relevant_entities": [],
    "active_threads": [],
    "important_npcs": [],
    "actors": {
      "npc_001": {
        "kind": "npc",
        "name": "严教官",
        "relationship_to_protagonist": {
          "label": "队友",
          "evidence": "并肩完成夜巡",
          "updated_turn": 7
        }
      }
    },
    "actor_context_index": {},
    "onstage_npcs": ["..."],
    "relevant_npcs": ["..."],
    "scene_objective": {},
    "immediate_goal": "...",
    "carryover_signals": [],
    "immediate_risks": ["..."],
    "carryover_clues": ["..."],
    "tracked_objects": [],
    "possession_state": [],
    "object_visibility": [],
    "graveyard_objects": []
  }
}
```

### Notes

- `onstage_entities` / `relevant_entities` 是前端推荐使用的实体展示结构
- 前端不应再自行用名字反查 `entity_id`
- `tracked_objects / possession_state / object_visibility` 是轻量物件状态层
- 这三层当前用于记录剧情相关物件、当前持有关系，以及该持有关系的可见性
- `actors.*.relationship_to_protagonist` 当前用于展示 NPC 与主角的长期关系标签，例如 `初识 / 相知 / 好友 / 队友`；该字段由 keeper 增量和 actor registry 绑定产生，不接受前端直接编辑
- 当前默认只记录“可持续追踪”的物件：
  - 有明确持有、展示、转移、搜出、收起、放下、遗失或证物化后果
  - 不会把短语残片、动作词片段或一次性货币默认塞进物件列表
- 已消耗、销毁、遗失或归档的物件会退出 active `tracked_objects / possession_state / object_visibility`，并可在 `graveyard_objects` 中保留生命周期标记
- `active_threads` 仍可能随 state 返回给调试使用，但不是默认用户可见主面板项目，也不作为 narrator 当前事实源

## GET /api/history

返回当前会话消息页。

### Query

- `session_id` 必填
- `before` 可选，整数光标；表示返回 `before` 之前的一页消息

### Response

```json
{
  "session_id": "story-live",
  "has_more": true,
  "next_before": 120,
  "total_count": 200,
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

- 默认每页最多返回最近 80 条消息
- 不带 `before` 时返回最后一页
- 带 `before` 时返回更早一页，适合前端“加载更早记录”
- 实际分页大小由 `runtime.json -> web.history_page_size` 控制
- 当前会话消息数未超过分页大小时，`has_more=false`，前端不会显示“加载更早记录”入口；超过分页大小时，前端在消息区顶部提供固定工具栏/内联按钮加载更早页。
- partial assistant 不作为已提交正文返回；旧 partial 历史会连同对应 user 输入一起过滤

## GET /api/entity

返回单个 scene entity 的详情。

### Query

- `session_id` 必填
- `entity_id` 必填

### Notes

- 对不存在的 `session_id`，当前会返回 `SESSION_NOT_FOUND`
- 这个接口当前不会再因为查询实体而隐式 bootstrap 新 session

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

### Frontend Note

- 当前前端不会再在设置页里管理 session
- 桌面端通过左上角 `用户 · 当前角色卡` 胶囊菜单 hover 展开最近会话下拉；点击胶囊仍打开“当前世界”设置
- 移动端通过输入区状态栏旁的向上箭头上拉最近会话菜单
- 两个入口都可切换、删除或开始新游戏

### Response

```json
{
  "sessions": [
    {
      "session_id": "story-live-20260406-203000",
      "replay": false,
      "active_preset": "world-sim-core",
      "bootstrapped_main_event": "开局：雨夜逢杀。"
    }
  ]
}
```

## POST /api/new-game

新建一个新的 session。当前不会归档或移动旧 session。

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

重新生成最后一条 narrator/assistant 回复。

默认保持旧行为：仅当最后一条 assistant 回复为 `partial` 时可用。前端重新生成按钮会传 `allow_complete=true`，允许对最新完整 narrator 回合执行“保留用户输入、替换 narrator 输出”的重生。

### Request

```json
{
  "session_id": "story-live",
  "allow_complete": true
}
```

`allow_complete` 可选，默认 `false`。

### Current Behavior

partial 回复路径会：
- 检查最后两条历史是否为 `user -> assistant(partial)`
- 回滚最后一对 user/assistant
- 回退 `last_turn_id`
- 按 `turn_id` 清理对应幂等缓存项
- 重新调用 `handle_message()` 生成该轮

完整 narrator 回复且 `allow_complete=true` 时会：
- 检查最后两条历史是否为 `user -> assistant(complete)`
- 读取最新 turn trace 的 `pre_turn.state` 与 `pre_turn.persona_layers`
- 回滚上一条 narrator 输出造成的 `state / persona / event_summaries / summary_chunks / keeper_archive / summary / meta audit` 派生影响
- 保留原用户输入作为该回合输入；最终 history 仍是同一条 user 后接新的 assistant
- 回退并重新提交同一个 turn 序号，清理指向旧 turn response 的幂等缓存

完整回合 regenerate 需要最新 turn trace；如果 trace 已被关闭或清理，会拒绝执行，避免只回滚 history 导致事实层不一致。

### Error

```json
{
  "error": {
    "code": "NO_PARTIAL_TURN",
    "message": "latest assistant reply is not partial"
  }
}
```

## POST /api/delete-latest-turn

删除最后一轮已提交的 `user -> assistant` 对，并回滚该轮 narrator / keeper 写入造成的派生状态。用于用户误触发送、输入有错别字或未写完时撤销最后一轮。

### Request

```json
{
  "session_id": "story-live"
}
```

### Behavior

- 只允许删除当前 session 的最后一轮，不支持删除历史中间轮次。
- 完整回合会读取最新 turn trace 的 `pre_turn.state` 与 `pre_turn.persona_layers`，恢复 `state.json` 和 session-local persona。
- 删除该 turn 的 `event_summaries` 项，清空 `summary_chunks` 与 `keeper_record_archive` 派生缓存，并重建 `summary.md`。
- `history.jsonl` 仍会作为 legacy 原始流水更新；24 轮 history shard 与 `history_manifest.json` 是派生缓存，会随 `save_history()` 重建。若 shard 缺失或过期，运行期读取会回退到 `history.jsonl`。
- 清理对应 `processed_client_turn_ids`、`turn_audits` 和 `last_turn_audit`，并回退 `meta.last_turn_id`。
- 如果最新完整回合缺少 turn trace，会拒绝删除，避免只删 history 而留下 keeper/state 污染。

### Response

```json
{
  "ok": true,
  "session_id": "story-live",
  "deleted_turn_id": "turn-0007",
  "deleted_user_text": "误触发送的输入",
  "messages": [],
  "state_snapshot": {}
}
```

### Error

```json
{
  "error": {
    "code": "TURN_TRACE_MISSING",
    "message": "latest turn trace is required to delete a complete turn"
  }
}
```
