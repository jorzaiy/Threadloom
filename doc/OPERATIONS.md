# Operations

**当前版本：v1.0**

## 定位

这个文件记录 `Threadloom` 当前原型的实际使用方式、调试习惯和边界，不是系统主配置。

## 当前常用脚本

日常主用：
- `backend/start.sh`：启动后端
- `backend/stop.sh`：停止后端
- `backend/import_character_card.py`：导入角色卡到当前角色 source
- `backend/import_sillytavern_chat.py`：导入 SillyTavern JSONL 聊天
- `backend/tools/replay_turn_trace.py`：单回合精确回放
- `backend/tools/rebuild_session_from_history.py`：从历史重建副本 session

已清理脚本：
- 旧历史迁移、审计与实验脚本已从仓库移除；当前不再保留 `backend/legacy_tools/`。

## 当前建议工作流

继续复用现有 `rp-agent` 资产：
- runtime 规则底板：`prompts/runtime-rules.md`
- 角色卡：`character/character-data.json`
- 世界书：`character/lorebook.json`
- 预设：`character/presets/*.json`
- 长期记忆：`memory/canon.md`
- 当前状态：`memory/state.md`
- 阶段摘要：`memory/summary.md`（当前仅作兼容/导入/调试层，不是 narrator 主输入）
- 原始流水：`memory/history.jsonl`
- NPC 档案：`memory/npcs/*.md`
- root persona seed：`runtime/persona-seeds/*`

`Threadloom` 不替代这些资产，而是在当前阶段把它们重新组织成 session-local runtime。

当前主角档案建议：

- 用户级基础档案：`runtime-data/<user>/profile/player-profile.base.json`
- 角色卡特化覆盖：`runtime-data/<user>/characters/<character_id>/source/player-profile.override.json`
- runtime 会先读基础档案，再叠加当前角色卡覆盖
- `USER.md` 不再进入 RP narrator 主链，只保留给通用协作备注
- narrator 运行时只消费一份收短后的玩家档案摘要，完整档案继续保留在 JSON 真相源中
- `player-profile.json` / `player-profile.md` 当前保留为兼容副本与可读导出

当前 narrator prompt 分层：

- 强约束层：玩家档案 slim 版、当前硬锚点、知情边界、最近窗口
- 连续性层：人物连续性表、活跃线程、重要物件、较早结构记录、相关 NPC 档案、Onstage Persona
- 候选知识层：系统级 NPC、可调入世界书 NPC、世界书基础护栏与 selector 命中的情境世界书片段

当前原则：

- 若强约束层与候选知识层冲突，一律以强约束层为准。
- 连续性层用于补 continuity，不可压过最近窗口与当前硬锚点。
- 候选知识层只表示“可以调用”，不表示“已经在场”或“当前已发生”。
- `【世界书基础规则】` 是蒸馏出的常驻护栏，不是完整世界书；它只用于避免硬设定、身份边界和规则口径漂移。
- `【情境世界书】` 由 selector 命中后优先回源到原始 `lorebook.json` 片段；普通回合不要把蒸馏摘要理解成“世界只有这些内容”。
- narrator 目标是维持一个会自己流转的 RP 世界：主角是参与者与观察者，不是唯一驱动器。
- 对回屋、关门、烧水、换位、短暂观察这类过渡段，narrator 仍应写出具体环境变化、人物反应、动作后的余波或正在累积的细节变化，不要塌成一句过短摘要。
- 只有当当前局势本来就存在追索、怀疑、风险、未决冲突或逼近感时，才继续强化压力；不要为了“有戏”而每轮硬塞危险感。
- `immediate_goal` 已从 narrator 主链降级，不再每轮常驻塞给 narrator。
- `main_event` 当前改为低频维护：默认只在早期 turn、周期点或明显场景切段时允许高频链重写。
- `location` 也已从高频自由抽取中降级，当前默认依赖首轮定底与 12 轮整理，不再每轮尝试从正文里扫地点短语。
- 若题材本身存在明确时间牌头习惯，runtime rules 已要求 narrator 优先给出稳定时间锚点再展开正文。
- 前端状态面板当前只展示有信息量的时间/地点行，不再把 `待确认` 和 `当前目标` 当常驻主信息显示。
- NPC 当前方向改为单列表：不再把 `在场 / 相关 / 重要 NPC` 作为 narrator 或 UI 的多套主显结构，而更偏向统一 registry / profile 入口。
- selector 当前会生成一层轻量 `npc_roster` 供 narrator 使用；keeper 继续维护全量 NPC 结构，但 narrator 主链不再直接依赖多套 NPC 分类。
- 当前 `npc_roster` 字段已收成：`name / role / status`，不再强求不稳定的 `tone / relation`。

当前 preset 定位：

- 默认 preset 名称由 `config/runtime.json -> sources.active_preset` 指定；当前主配置为 `world-sim-core`。
- preset 文件经 `backend/paths.py` 的分层路径解析加载，不再承诺固定存在于 `runtime-data/default-user/presets/`。
- preset 现在主要负责：节奏、镜头重心、外部推进倾向、注入预算。
- 世界真相、主角控制权、知情边界、世界自主流转等长期规则，优先由 `prompts/runtime-rules.md` 负责。

当前 `config/runtime.json` 已收回到最小主链用途：

- `sources`
- `memory`
- `model_defaults`
- `entity_recovery`
- `web`
- `trace`

旧的 `bootstrap`、大部分 `refresh_policy`、以及没有实际控制力的 `state_policy / persona_policy` 已移除；它们不再是真实控制当前主链行为的配置入口。
`summary` 也已从 `sources` 主配置中降级；当前保留的 `summary.md` 主要用于导入兼容、trace 与历史层，不再作为 narrator 主链输入。

当前 active_threads 约束：

- thread continuity 主要继承 `thread_id`，不再为了延续性强行复用已经过时的 `key`。
- 当风险/线索内容本身已经换成新阶段时，`key` 应与当前 `label` 同步更新，避免旧风险名挂在新内容上。

## 角色卡导入

当前推荐把角色卡导入到当前用户/当前角色卡的 source 目录，而不是继续手工编辑旧共享 `character/` 目录。

导入命令：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.png
```

或：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.raw-card.json
```

导入后当前角色卡 source 目录会生成：

- `character-data.json`
- `lorebook.json`
- `openings.json`
- `system-npcs.json`
- `import-manifest.json`
- `assets/`
- `imported/`

当前设计原则：

- `character-data.json` 只保留角色核心
- `lorebook.json` 只保留世界知识
- `openings.json` 单独保存开局模式、开局文本/菜单与 bootstrap
- 单 `first_mes` 卡导入为 `mode: direct`，运行时直接展示开局，不显示“可用开局 / 随机开局 / 报数字”提示
- 多个 `alternate_greetings` / `group_only_greetings` 候选才导入为菜单开局
- 开局文本里的 SillyTavern 基础占位符会被替换：`{{char}}` 为角色名，`{{user}}` 为 `玩家`
- `system-npcs.json` 单独保存系统级 NPC：
  - `core`
  - `faction_named`
  - `roster`
- 当前运行时默认只优先消费 `core`
- `assets/` 单独保存封面和缩略图

## 最小启动

推荐：

```bash
cp /root/Threadloom/.env.local.example /root/Threadloom/.env.local
cd /root/Threadloom/backend
./start.sh
```

说明：
- `backend/start.sh` 会自动加载 `/root/Threadloom/.env.local`
- 后端默认只监听 `127.0.0.1:8765`。如需远程访问，应通过可信反向代理暴露，不建议直接改成公网监听。
- 推荐把真实密钥只放在 `.env.local`，`config/*.json` 中使用 `env:VAR` 引用
- 修改站点 URL 时若没有重新输入 API Key，运行时会清空旧密钥，避免旧 key 被转发到新 endpoint。
- 远程 provider URL 必须使用 HTTPS；本机模型服务可继续使用 `localhost` / `127.0.0.1`。
- 当前用户自己的站点与模型配置会写到 `runtime-data/<user>/config/`
- `config/runtime.json` 继续承载共享内容层与全局策略，不再作为用户站点管理的主存储
- turn trace 默认关闭；仅在需要排查 prompt/context 问题时显式启用，并注意 trace 文件会包含敏感上下文。
- 当前用户模型/站点文件：
  - `runtime-data/default-user/config/site.json`
  - `runtime-data/default-user/config/model-runtime.json`
- 默认产品面仍可按单用户 `default-user` 使用；启用多用户后，前端和 API 会进入正式认证/用户管理流程
- `/api/auth/login`、`/api/auth/logout`、`/api/users`、`/api/multi-user` 是 v1.0 多用户流程的一部分；state-changing 请求使用 Bearer token
- 多用户运维以 `runtime-data/_system/users.json` 为账号真相源；`runtime-data/<user>/` 目录只表示数据存在，不等于可登录账号
- 管理员禁用普通用户会保留 `runtime-data/<user>/`，但立即撤销该用户所有 token；归档删除会把目录移动到 `runtime-data/_system/deleted-users/` 后再删除账号记录
- 用户管理页会提示 orphan user dirs 与 deleted archives；这些提示用于人工判断历史/测试残留，不会自动清理
- 启动时后端会把 `_system/users.json` 与 `_system/sessions.json` 权限收紧到 `0600` 并 prune 过期 sessions
- 当前设置页已简化为单站点模式：
  - 用户只维护一个站点 URL / API Key / API 类型
  - 先点“获取模型”
  - 再给 Narrator / State Keeper 选模型
  - `temperature / max_output_tokens` 不再暴露给普通用户，统一走 `config/runtime.json -> model_defaults`
- 高级角色配置：
  - `turn_analyzer`
  - `arbiter`
  - 当前可通过 `runtime-data/default-user/config/model-runtime.json -> advanced_models` 手动覆盖
  - 暂不进入普通设置页
  - `state_keeper_candidate` 不再接受独立模型覆盖，固定继承设置页中的 State Keeper 模型

也可以直接：

```bash
cd /root/Threadloom/backend
python3 server.py
```

停止：

```bash
cd /root/Threadloom/backend
./stop.sh
```

健康检查：

```bash
curl http://127.0.0.1:8765/api/health
```

默认地址：

```text
http://127.0.0.1:8765
```

## 当前可用能力

当前已接通：
- `GET /api/sessions`
- `POST /api/message`
- `POST /api/new-game`
- `POST /api/delete-session`
- `POST /api/regenerate-last`
- `GET /api/state`
- `GET /api/history`
- `GET /api/entity`
- `GET /api/characters`
- `POST /api/character/select`
- `POST /api/characters/import`
- `POST /api/chat/preview`
- `POST /api/chat/import`

当前前端支持：
- 点击底部当前会话名，展开最近会话下拉
- 最近会话下拉支持切换、删除、开始新游戏
- 最近会话按最后一条消息时间从新到旧排列
- 发送消息
- partial 时重新生成上一条
- 底部浮动状态面板和 NPC 详情查看
- 折叠调试区
- 居中设置弹窗

## 当前运行特点

当前 prototype 的重要行为：
- 新 session 会从 root `canon / summary / state` bootstrap，不从空壳 state 起步
- opening 已经是独立状态机，不再只是输出一段开局提示
- 开局选择后的首轮 narrator 正文现在会直接接入首轮 keeper 写回：通常能落下时间/地点/主事件/在场人物/风险等基础状态，不再只留一个 opening 壳 state；`immediate_goal` 当前仍可能偏保守或回到 `待确认`
- 首个 narrator 回合会用大预算注入原始 alwaysOn/foundation 世界书片段给世界定底；后续普通回合改为“蒸馏基础护栏 + selector 回源原文片段”，避免 raw lore 每轮压过最近 12 轮
- 同一 `session_id` 的 HTTP 写请求现在会串行执行，降低并发覆盖风险
- 每个 turn 现在会额外落一份 `turn-trace/turn-XXXX.json`，用于单回合精确回放
- `runtime.json -> trace.enabled / trace.keep_last_turns` 可控制 trace 是否启用以及最多保留多少轮
- narrator 正文生成现在先用主 narrator 模型重试 3 次；主模型均失败后，使用 `state_keeper.model` 作为副 LLM 再重试 3 次。副 LLM 接管会在 response / turn trace 的 `narrator_retry` 中标记 `provider_used: secondary`。
- 若主/副 narrator 全部失败，本轮返回空 `reply` 与 `NARRATOR_UNAVAILABLE`，不写 assistant 历史、不递增 turn、不更新 state，trace 标记 `not_committed: true`，避免沉浸式 RP 中出现硬编码 fallback 文案。
- partial assistant 回复不会作为已提交正文显示；生成阶段会自动重试，重试耗尽后返回状态栏错误，`/api/history` 与后续 prompt recent window 会过滤旧 partial 轮次及其对应 user 输入
- narrator 若明显停在半句中间，即使 provider 没返回 `finish_reason`，当前也会按 incomplete 处理，避免把坏输出继续写坏 state 或污染下一轮上下文
- `regenerate-last` 会回滚最后一对 `user -> assistant(partial)` 再重试
- `state_keeper` 优先，`state_updater` 兜底
- `state_keeper` 现在会拒收明显低信号或相对上一轮明显退化的 state
- `state_fragment` 现在会先作为结构化锚点进入 narrator 与 state_keeper
- `state_keeper_candidate` 固定继承 `state_keeper` 的实际模型，不再通过 hidden advanced 配置单独分模。
- `state_keeper_candidate` 现在可以作为 `skeleton keeper` sidecar 先产出最小骨架，再并入 `state_fragment`；当前每个完整回复后都会运行，模型固定继承 State Keeper。它只维护 `time / location / main_event / onstage_npcs / immediate_goal` 五个骨架字段
- 首轮 bootstrap 不跑 skeleton，直接走一次完整 `state_keeper` 定底
- opening-choice 的首轮正文当前例外：会先跑一次 skeleton keeper 定骨架，再跑 fill keeper 补风险/线索/物件，避免首轮正文写出来但 state 仍停在开局壳；这条链当前不等同于普通非合并轮的 `update_state()` 路径
- 当前 keeper 相关模型使用同一站点配置，可在设置页或 `model-runtime.json` 中切换，不再在代码中维护固定模型分工。
- 完整 `state_keeper` 当前已切到 `fill-mode`：默认只在骨架状态上补 `immediate_risks / carryover_clues / tracked_objects / knowledge_scope` 这类次级字段，而不再整份重写 state
- `carryover_signals` 统一信号层现已真实落盘到 state：用于承接后续仍会影响局势推进的 `risk / clue / mixed` 信号；旧 `immediate_risks / carryover_clues` 仍保留兼容，并优先从统一信号层派生
- 普通 `state_updater` 路径当前也会补 `carryover_signals`，不再只在 full fill keeper 回合里出现；快照层与部分消费点已开始优先使用统一信号层，再兼容旧风险/线索字段
- `immediate_goal` 当前主要影响 `active_threads` 的 goal/主线程标签候选、世界书触发词与 summary 展示；它已不再作为 narrator 主链里的强锚点，当前稳定性仍低于 `time / location / main_event`
- `main_event` 当前不再无条件反压主线程 `label`：只有当 `main_event` 自身质量明显更高，或主线程标签仍是低质量占位时，才会接管主线程标签；避免低频事件锚点把更快更新的 `active_threads` 主线压回旧值
- `active_threads` 当前已做去主导化实验：线程层仍继续落盘并保留给 debug/state 观察，但 `【活跃线程】` 已退出 narrator prompt，selector 也不再把 thread 当主要触发依据；当前方向约束更偏向 `recent window + carryover_signals + event recall`
- 当前目标分工草案：
  - `event`：3 回合级中程检索层，默认不给 narrator 常驻输入
  - `summary`：12 回合级长程压缩层，只在 selector 判断需要时回流
  - `signal`：当前方向约束层，可直接进入 narrator / selector
  - `thread`：state/debug 辅助层，不再默认承担 steering 职责
- `event` 当前真实行为已更接近这份草案：
  - 每 3 轮写入一次 `event_summaries`
  - 事件总结当前已真正读取最近 `1~3` 对 turn 窗口，而不是只看当前轮 narrator prose
  - fallback event summary 当前已不再优先抓天气/氛围句，开始更像阶段事件压缩；后续若继续打磨，主方向应是 clue/risk 的结构化质量，而不是继续扩大窗口
- NPC / object / clue registry 当前已改为批量刷新：默认累计到至少 3 个新的对话对后才触发一次 sidecar 更新，不再每轮都检查一次 gemma
- entity candidate judge 当前已收成单一入口：保留 `state_updater.py` 中的判定，移除 `state_bridge.py` 中的重复 judge，减少每轮额外 gemma 调用
- 调试面板当前会优先显示 `event_summary_count / event_hits / inject_summary / latest event summary`，用于观察双层检索是否真的在工作
- 轻量物件状态层已接入：
  - `tracked_objects`
  - `possession_state`
  - `object_visibility`
- 物件层当前已可在真实 live 回合中落下基础结果：
  - 物件可进入 `tracked_objects`
  - 玩家持有可映射到主角名
  - 物件可见性可写回 `object_visibility`
  - `纸条 / 短刀` 这类动作物件已可在 live 验证中进入 `tracked_objects`
- 当前物件层额外约束：
  - 只记录具有可持续物理状态的物件
  - 不把短语残片或动作词片段误识别成物件
  - 一次性付款、零散货币、临时消耗品默认不进入物件列表，除非后续会被持续追踪
  - 已进入列表的低价值临时物件，若后续几轮都没有再次出现，且没有持有/可见性/关键类型锚点，也会自动降级移除
- 若 `state_keeper` 失败，当前会先走 `fragment-baseline`，再让 heuristic fallback 在其上补细节
- `state_keeper` 不可达时，物件状态 fallback 已不会再因为正则模板格式化错误而崩掉；此时仍可正常产出 turn trace
- fallback `state_updater` 现在更偏保守继承，不轻易覆盖已有高信号字段
- 对已经被旧 heuristics 污染的会话，当前可以用离线重建方式直接修 `state / active_threads / important_npcs / summary`
- summary 基于 state 和最近 turn 重写，不再直接摘 narrator prose
- state snapshot 现在直接给前端 `onstage_entities / relevant_entities`
- `default_debug / show_debug_panel / history_page_size` 已从配置贯通到 API 和前端
- 前端消息区支持通过“加载更早记录”按钮向上分页，不再只看最后一页
- 当前浮动状态面板是 v1.0 结构状态视图：
  - 时间 / 地点硬锚点
  - 主要事件
  - 在场 / 相关 / 重要 NPC
  - 关键物件
  - 活跃线程
- `onstage_npcs` 当前已开始收向 `scene_entities` 的投影结果：keeper 更偏先维护 `scene_entities`，再由状态归一化层根据 `scene_entities[].onstage` 投影当前在场名字列表，减少双写漂移
- 前端默认会话选择已切到“最近更新的活动会话优先”，不再固化到 `story-live`
- 角色卡管理已改到设置面板中，支持读取角色卡元数据和缩略封面图
- narrator prompt 已加入更通用的知情边界约束，减少 NPC 间自动共享私下信息
- 所有文件写入（`runtime_store.py`、`keeper_archive.py`）已改为原子写入：先写临时文件 → fsync → `os.replace`（POSIX 原子），防止崩溃/断电导致数据损坏
- 模型调用层（`model_client.py`、`local_model_client.py`）已加入 `_retry_on_rate_limit` 装饰器：429/503 错误自动指数退避重试（最多 3 次），尊重 `Retry-After` 头
- state 中的 `knowledge_scope` 字段只保留本轮新增知情 delta：包含 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`，由 keeper 按回合提取增量，`state_bridge.py` 清洗但不长期合并；长期知识由 `actor_registry.py` 派生到 actor-id 版 `knowledge_records`，并做轻量相似去重，`narrator_input.py` 渲染为结构化知情边界
- state 中新增 `resolved_events[]` 字段：线程经 `active → watch → cooling_down → resolved` 状态机过渡后归档（最多 20 条）
- thread tracker 已改用按类型分级的保留策略 `THREAD_RETENTION_CONFIG`（main:4, risk:3, clue:2, arbiter:1），替代旧的统一 `THREAD_RETENTION_TURNS`

## 当前适合怎么调试

### 2026-04-16 实测补充

本轮新增了一次真实 HTTP 长跑验证，重点不再是“链路能不能跑”，而是：

- 开局选择是否正常落到 runtime 主链
- 世界书与系统级 NPC 候选是否真的进入 narrator prompt
- `12` 对 recent window 是否真的作为 narrator 主上下文
- keeper archive 是否会在窗口外真实回流
- 长跑后 state / threads / important_npcs 是否出现明显漂移

当前已确认：

- 系统级 NPC 候选与世界书预算注入已真实进入 narrator prompt
- `12` 对 recent window 已真实生效
- recent window 在 narrator prompt 中按完整正文注入，不再按短摘要截断；连续性问题优先检查 turn trace 的 `【最近12轮完整上下文】` 是否包含上一轮关键变化
- keeper archive 在记录真正掉出 recent window 后，会以 `【较早结构记录】` 真实进入 narrator prompt
- HTTP 层已修：客户端提前断开时，backend 不再把已完成请求伪装成 `500`，只记录轻量断连日志

本轮仍暴露的主要精度问题：

- 场景实体与重要人物的别称归一仍需持续收紧，特别是：
  - `毡笠人 / 毡笠身影`
  - `暗影 / 皂衣人`
- 这类问题当前更像 scene entity merge / important NPC alias 过滤不够保守，不是 narrator 主链中断

建议优先用这几种方式：
- 直接在前端页面手动跑一个真实 session
- 用 `GET /api/state` 和 `GET /api/history` 看写回是否稳定
- 直接看 `sessions/<session_id>/turn-trace/turn-XXXX.json`，确认本轮 pre-turn / narrator / keeper / post-turn 是否符合预期
- 若当前环境下 narrator / keeper 模型不可达，可先手动跑一轮拿到 `NARRATOR_UNAVAILABLE` trace，重点检查 `narrator.retry_trace / prompt_block_stats / selector`，再用单回合回放调 `threads / important_npcs / persona / summary`
- 看调试区里的：
  - `arbiter_analysis`
  - `arbiter_results`
  - `state_keeper_diagnostics`
  - `retained_threads`
  - `retained_entities`
- 用 replay 脚本检查 continuity 和 thread 漂移

回放脚本：

- 当前仓库已不再保留旧的 `scripts/replay-runtime-web.py`。
- 单回合或副本重放，当前以 `backend/tools/replay_turn_trace.py` 与 `backend/tools/rebuild_session_from_history.py` 为主。

单回合精确回放：

```bash
cd /root/Threadloom
python3 backend/tools/replay_turn_trace.py --source-session story-live --turn-id turn-0012 --target-session replay-story-live-turn-0012
```

说明：
- 这条链不重新开局，也不重新发送整段历史
- 它会从 `runtime-data/default-user/characters/<character_id>/sessions/<source>/turn-trace/turn-XXXX.json` 里恢复该回合的 pre-turn 状态与人格层
- 然后只重跑该回合的后半段写回链，适合快速调 `threads / important_npcs / persona / summary`

SillyTavern 聊天导入：

```bash
cd /root/Threadloom
python3 backend/import_sillytavern_chat.py --source '/root/Threadloom/tmp/你的聊天记录.jsonl' --target-session import-your-chat-001
```

当前第一版行为：
- 支持导入单角色 SillyTavern `jsonl` 聊天导出
- 首行 `chat_metadata` 会单独保留到 `imports/sillytavern-chat-metadata.json`
- 原始导出文件会复制到 `sessions/<session_id>/imports/`
- 消息正文只导当前采用的 `mes`
- `extra.reasoning`、`swipes`、`swipe_info` 当前不会进入 Threadloom 主历史

当前第一版边界：
- 还不处理 group chat
- 还不保留 swipe 分支到 Threadloom 历史
- 导入后只是先生成 session 与 `history.jsonl`
- 后续仍建议再接一次 replay / state 重建，把 `state / summary / persona / threads` 真正建起来

当前 history-only 重建链补充：
- `backend/tools/rebuild_session_from_history.py` 现在支持：
  - `--target-session`
  - `--force-recreate`
- 推荐总是在副本 session 上做离线重建测试，不直接覆盖原始导入档。
- 当前 `state` 主路径在副本测试里的最新状态：
  - `onstage / scene_entities` 已明显变干净
  - `relevant_npcs` 已能非常有限地补回稳定离场人物
  - `active_threads` 已可稳定收成 `main / risk / clue`
  - 长窗口下旧幽灵实体不会再回流污染现代题材样本
  - 物件层在导入样本中已能开始产出 `tracked_objects / possession_state / object_visibility`

当前存档分层重构进度：
- 目标结构已经明确为：
  - 用户层：`player-profile.base.json`、兼容 `player-profile.*`、`presets/`
  - 角色卡层：`character-data.json`、`lorebook.json`、`canon.md`、静态 NPC 资料
  - session 层：`history/state/summary/persona/trace/imports/meta/context`
- `backend/paths.py` 与核心 store/lifecycle 模块已开始接入这套三层路径模型。
- 现在已经有显式来源抽象：
  - `user.*`
  - `character.*`
  - `session.*`
- 新路径模型已能描述用户层 / 角色卡层 / session 层的目标目录，而不是只靠旧的平铺 `sources` 字符串路径。
- 当前兼容层仍保留 legacy root 路径解析，但主工作路径已经切到 `runtime-data/<user>/characters/<character_id>/sessions/`
- 当前结论：暂不急着上数据库记录元数据；先把目录分层、显式来源解析和迁移链做稳，再评估是否需要 SQLite 之类的元数据层。
- 旧历史迁移、审计与实验脚本已删除；当前只保留仍用于调试的 `backend/tools/replay_turn_trace.py` 与 `backend/tools/rebuild_session_from_history.py`。

四要素现状：
- 时间：已接近可用，优先吃场景头与显式时间推进，稳定度较高。
- 地点：已接近可用，优先吃场景头与显式转场，稳定度较高。
- 人物：当前最接近可用，`onstage / relevant / scene_entities / important_npcs` 已基本进入可控状态。
- 事件：已可用，但 `main_event / goal / risks / clues` 的文案仍偏模板化，后续更像体验优化而非结构修 bug。
- `main_event` 当前已能在 opening 首轮和普通 live 回合中较稳定落下；`immediate_goal` 仍是这组字段里最不稳定的一项。
- 物品：链路已通，且已在 live 回合中成功落下基础结果；当前主要剩余问题是精度、归一化和部分动作物件的稳定性。
  - 当前 keeper 侧已支持把 `player_inventory / protagonist / 主角 / 玩家 / 自己` 这类值归一化到主角名。

空白起步与首页加载补充：
- 现在前端与后端都已修正：
  - 当 session 列表为空时，不再默认用 `story-live` 自动请求 `history/state`
  - `/api/sessions` 在空列表时，`default_session_id` 现在返回空字符串，不再硬塞 `story-live`
  - `/api/history` 与 `/api/state` 对不存在的 session 现在只返回空结果，不会顺手 bootstrap 出一个新目录
- 这意味着：
  - 清空当前角色卡下的 session 后，页面保持空白等待用户点击“开始新游戏”
  - 空态卡片里的“开始新对话”与 Session 管理里的“开始新游戏”现在走同一条 `/api/new-game` 初始化路径
  - 不会再因为页面初始化而自动长回 `sessions/story-live`
- 当前首页变慢的判断：
  - 主要风险更像是 session 列表过多时的枚举与排序，而不是封面图本身
  - 角色卡缩略图当前文件约 `267 KB`
  - 已给 `/character-cover` 增加缓存头，减少重复加载成本

## State Notes

最近一轮与 state 相关的关键结论：
- `state_updater.py` 主路径已经继续收向“previous-state-driven merge + 保守候选过滤”，不再走题材补丁路线。
- `extract_generic_character_names()` 与 `state_bridge._looks_like_continuity_name()` 已补上通用过滤，抽象概念 / 系统机制词不会轻易进入人物池。
- `碎影江湖` 与 `血蚀纪` 的 clean session 真实 HTTP 回归都已验证：`scene_entities / important_npcs / relevant_npcs / continuity_candidates` 当前保持干净。
- `relevant_npcs` 当前仍采用非常保守的补回策略，优先少报，避免把弱信号人物或抽象词重新带回状态层。
- 物件层已经进入“live 可用、继续精修”的阶段；当前主剩余问题偏向归一化与展示文案，而不是链路污染。

当前建议：
- 在线真实 HTTP 回归仍优先于离线重建样本。
- 需要做破坏性验证时，继续优先在副本 session 上测试，不直接污染原始导入档。

## 当前已知边界

当前仍属于原型的部分：
- narrator 已接入真实模型，但 state 仍主要靠 prose 反提
- arbiter 已接进主链，但还是 heuristic 版本
- `turn_analyzer` 默认仍是 heuristic
- persona 流转已接入，但规则仍偏保守启发式
- 世界书人物注入已接入，但还不是独立调度层
- 前端没有编辑能力，错误恢复也仍较薄
- `runtime.json` 里的部分 web 配置项还没完全生效到 UI

## 当前已知问题

目前最值得盯的几类问题：
- `state_keeper` 失败后 fallback state 虽已更保守，但仍可能过于空泛
- 一次性服务 NPC 仍可能偶发被高估重要性
- 同名实体仍没有完整的 disambiguation 交互，当前只是后端直出实体列表并在歧义时保守展示
- summary / important NPC / thread tracker 之间仍可能互相放大弱信号
- 主角目前还没有独立的 runtime 层，observer/主角信息仍需要继续和 NPC 层做强隔离
- ~~已解决事件还没有独立事件归档层~~ → 已补 `resolved_events`：线程经 `cooling_down` 过渡后归档到 `state.resolved_events[]`（最多 20 条）
- ~~信息隔离仍主要靠 prompt 约束~~ → 已补 `knowledge_scope`：state 中新增 `protagonist.learned[]` 和 `npc_local.{name}.learned[]`，keeper 按回合提取增量，narrator_input 渲染结构化知情边界
- 物件状态层已经接线完成，但当前真实回合中的抽取强度还不够；链路已通，实际产出仍需要继续调强
- 当前单回合精确回放已优先覆盖 runtime 主链；opening 菜单态暂不作为主要回放目标
- `state_updater.py` 当前仍处于主路径重构中；旧 heuristics 已被证明会对异题材记录产生幽灵状态，明天应继续把它们下沉到 legacy fallback

## 当前配模建议

当前更推荐的分工是：
- narrator：继续使用更强的远端模型。
- state_keeper：使用设置页选中的 State Keeper 模型，同时承担 skeleton keeper 与 fill keeper。
- narrator 失败重试后会使用 State Keeper 模型作为副 LLM 兜底生成正文。
- heuristic：仅作为结构化写回的最终兜底。

原因：
- narrator 是中文长上下文 RP 质量的上限，不适合轻易降到小模型。
- keeper 任务更偏结构化提取，通常可以选择比 narrator 更便宜、更快的模型。
- skeleton keeper 与 fill keeper 均复用 State Keeper 模型配置，输出上限由角色模型配置和 `config/runtime.json -> model_defaults.state_keeper` 控制。

## 运行原则

当前最重要的顺序仍然是：
1. 先稳 `state`
2. 再稳 `summary`
3. 再稳 `threads / important_npcs / persona`
4. 最后再打磨 UI 和更细的自动化
