# Threadloom

**当前版本：v1.0**

Threadloom 是一个面向长期角色扮演与世界模拟的 runtime-first Web 应用。

它的核心思路不是把聊天记录当成唯一真相源，而是把这些层作为主事实面：

- `canon`
- `state`
- `persona`
- `threads`
- `recent window`
- `keeper archive`

前端负责消息收发、会话切换和状态展示；后端负责上下文装配、裁定、叙事生成与事实写回。

说明：
- `summary` 当前仍会保留为 session-local 写回 / 调试产物
- `summary` 当前不再作为 narrator 主输入

## 当前定位

当前 v1.0 目标是把“本地可用、角色卡可替换、可选多用户”的 RP runtime 做成稳定主线，而不是把它扩展成通用 SaaS 平台。

当前边界：
- 默认即单用户模式，与之前体验一致
- 多用户模式可由管理员（`default-user`）从设置面板启用：启用前必须先设置管理员密码
- 角色卡当前可替换，但产品形态仍偏"当前激活卡"
- 站点连接（baseUrl / apiKey / 模型列表）始终全局：在多用户模式下由管理员维护，普通用户只读
- 模型分配（Narrator / State Keeper）与 Preset 选择按用户存储，互不影响

后续方向：
- 多角色卡：继续打磨导入后的 runtime 清洗与管理体验
- 多站点：若后续确实需要，再扩展为高级配置，而不是先把普通设置页做复杂
- 忘记密码恢复 / 双因素认证 / SSO：本次 UI 不在范围，需要时再单独立项

## 当前能力

- 经过全面翻新优化的沉浸式极简 Web UI：
  - 右侧抽屉式毛玻璃（glassmorphism）高级设置面板，集成角色卡切换（水平轮播卡片）
  - 极简的顶部悬浮工具栏与账号管理面板（单/多用户模式）
  - 发送按钮内置呼吸指示灯，搭配全局悬浮药丸提示，释放干净的输入空间
  - 聊天气泡及输入框采用毛玻璃（blur）质感悬浮设计，列表边缘支持优雅渐变淡出
- 多 session 切换、新游戏、删除会话、partial regenerate
- narrator / analyzer / keeper 分模
- session-local `state / summary / persona / threads / important_npcs`
- skeleton keeper + fill-mode keeper 的双层状态链
- session 级串行锁与 partial 污染隔离
- session 与当前角色卡有隔离校验：旧角色卡下的同名 session 不会在切卡后被静默继续使用
- 动态角色卡名称、副标题与侧栏封面图
- **泛化架构**：所有卡特定逻辑已从代码移到 `character-data.json["hints"]`，支持任意角色卡
- API Key 支持环境变量引用（`$VAR` 或 `env:VAR`）
- API 韧性：模型调用自动重试 429/503 错误（指数退避，最多 3 次，尊重 `Retry-After`）
- 安全加固：后端默认仅监听 `127.0.0.1`，API 响应带基础安全头，请求体有大小上限，provider URL 会阻止常见 SSRF 目标
- 多用户模式（可选启用）：管理员密码 + bcrypt 校验、登录失败计数与锁定（5 次失败锁 15 分钟）、进程内登录限速、Bearer token 认证（30 天 TTL，按用户限制活跃 token 数，state-changing 拒绝 Cookie auth）、IP-pinned 出站连接防 DNS-rebinding、per-user session/character 配额、自助改密、用户禁用/启用/归档删除、孤儿数据目录归档、用户管理与多用户开关向导
- 原子文件写入：所有 state/archive 写入防崩溃/断电数据损坏
- 结构化知情边界：`knowledge_scope` 独立追踪主角和各 NPC 已知信息，替代纯文本软约束
- 线程生命周期管理：按类型分级保留、`cooling_down` 过渡态、`resolved_events` 归档
- turn trace 支持通过 `trace.enabled` 和 `trace.keep_last_turns` 控制是否落盘及保留数量
- 角色卡导入采用 v1.0 分层产物结构：
  - `character-data.json`
  - `lorebook.json`
  - `openings.json`
  - `system-npcs.json`
  - `import-manifest.json`
  - `assets/`

## 当前 narrator 主链

当前 narrator 主输入不是单纯“两层上下文”，而是一个 runtime-first 分层装配：

强约束层：
- `runtime-rules`
- `preset`
- `character_core`
- `世界设定锁`：角色卡定义的世界观、时代、题材、身份边界、世界机制与核心关系不可被本轮用户输入或旧历史改写
- `player_profile`
- `canon`
- 当前硬锚点（`time / location`）
- 知情边界（`knowledge_scope` + 固定规则）
- 结构化状态锚点（来自 `state_fragment`，不含 `immediate_goal`）

短期场景事实层：
- 最近 `12` 对 `user/assistant` turn
- 本轮用户输入

短期层只负责承接当前场景、行动链、位置、视线范围、控制关系和即时后果；它不能把当前角色卡切换成另一个题材、时代、世界机制或人物身份。用户主角只是 RP 世界内的一个角色，不是作者、导演、GM 或世界主宰；用户可以尝试行动和表达态度，但不能直接指定 NPC 服从、行动必然成功、关系成立、物品凭空出现或客观结论生效。

连续性层：
- `npc_roster`
- `active_threads`
- `tracked_objects / possession_state / object_visibility`
- `keeper archive`
- 条件注入的 `npc_profiles`
- `persona`

候选知识层：
- 条件注入的系统级 NPC
- 条件注入的世界书 NPC 候选
- 条件注入的世界书正文
- 条件注入的长程阶段摘要

候选知识、召回历史与用户输入都要先经过当前角色卡世界的一致性判断。防污染不依赖固定关键词表，而是比较整体语境、因果规则、时代感、社会制度、技术/超自然边界、人物身份与当前角色卡世界是否兼容。narrator 需要保持世界独立性和阻力，不应为了讨好用户而让 NPC 无条件配合、让风险消失或让越权输入直接变成现实。

当前明确不再作为 narrator 主输入骨架的内容：

- `summary` 不是默认常驻主输入
- 独立 `mid digest` 已降级
- 旧 `memory agent` recall 不再主导 narrator
- 世界书注入受 selector 和预算约束，不再默认整块灌入

当前世界书预算已细化到条目类型：

- foundation 底板条目单独限额
- situational 场景条目单独限额
- `rule / world / faction / history / entry` 可分别控制注入数量
- `archive_only` 条目不会进入 narrator

## 角色卡管理

当前 Web UI 已支持当前用户范围内的角色卡管理：

- 设置面板内可切换当前用户的角色卡
- 设置面板内可直接导入新的角色卡文件（`.png` / `.json`）
- 角色卡枚举范围只限于当前用户目录下的 `runtime-data/<user>/characters/`
- 角色卡导入与聊天导入使用请求局部 override，避免并发导入时串写到其他角色卡目录
- 当请求局部 override 设置时，`character-data / lorebook / npc / persona / player-profile` 等 layered 读路径不会再回退到仓库根 `character/` 或 `memory/`，杜绝并发导入下被另一张卡的 shared 内容串写
- `card_hints` 与 `protagonist_names` 缓存按 `(user_id, character_id)` 维度，不再使用进程级 `lru_cache`，并发请求看到的是各自的 hints / 主角名
- history 缓存按实际 `history.jsonl` 路径隔离，不再只按 `session_id` 复用
- persona seed 默认只读取当前角色卡 source 与 session-local 层，不再静默回退到共享 `runtime/persona-seeds`
- 当前默认且唯一用户会显示为 `default_user`
- 启用多用户模式后，管理员可在设置面板创建普通用户、重置密码、禁用/启用账号或归档删除账号

## 多用户模式

默认启动后是单用户模式，与之前的体验一致；不强制登录、不暴露认证 UI。需要让多个人同时使用时，管理员可以在设置面板里启用多用户模式。

### 启用多用户的流程

1. 管理员（`default-user`）打开 **设置 → 用户管理**
2. 点击 "启用多用户模式 / 设置管理员密码"
   - 若管理员尚未设置密码：弹窗输入并二次确认（至少 12 位）
   - 若已有密码：弹窗确认密码即可
3. 后端会清空所有 sessions（包括当前 admin 的 token），前端拿刚输入的密码立刻**静默重登**，无需手动跳登录页
4. 重载完成后，顶栏会显示 "管理员 · default-user"，"用户管理" tab 可见

关闭多用户：在同一位置点击 "关闭多用户模式"，输入密码确认。所有用户立即注销。

设置页只展示必要状态与操作；会话失效、角色权限和数据目录处理规则以本文档为准。

### 用户角色与权限

| 资源 | 管理员 (`default-user`) | 普通用户 |
|------|-------------------------|----------|
| 站点连接（baseUrl / apiKey / 模型列表 / provider） | ✅ 可读可写（全局唯一来源） | 🔒 只读，apiKey mask |
| 模型分配（Narrator / State Keeper） | ✅ 自己一份 | ✅ 自己一份 |
| Preset 选择 | ✅ 自己一份 | ✅ 自己一份 |
| 角色卡导入 / 切换 | ✅ 不限 | ✅ 上限 10 张 |
| Session 创建 | ✅ 不限 | ✅ 每角色卡上限 50 |
| 自助改密 | ✅ | ✅ |
| 用户管理（创建 / 重置密码 / 禁用 / 启用 / 归档删除） | ✅ | ❌ |
| 多用户模式 toggle | ✅ | ❌ |

普通用户的 site 路径在后端真正全局：`runtime-data/default-user/config/site.json` 是唯一来源，普通用户调 `/api/site-config POST` 直接 403。

### 认证与安全

- Token 存储：`localStorage['tl_session_token']`，TTL 30 天；主动登出会立即失效
- 传输：`Authorization: Bearer <token>` 头，state-changing 请求（POST/DELETE/PUT）拒绝 Cookie auth 防 CSRF
- Session 校验：服务端只接受仍存在且未禁用用户的 token；每个用户最多保留 10 个活跃 token，超过后淘汰最旧 token
- 登录失败计数：连续 5 次错误密码自动锁 15 分钟，成功登录或 admin 重置密码立即清零
- 登录限速：后端对登录请求做进程内 per-IP 与全局窗口限速，降低暴力尝试成本；该限速不替代反向代理或公网部署时的外部限流
- 用户枚举：登录路径在用户不存在时也跑一次 dummy bcrypt，使响应时间不可区分
- 自助改密：保留当前 token，撤销该用户其他设备所有 token
- 用户禁用：管理员禁用普通用户时立即撤销该用户全部 token，但保留其 `runtime-data/<user>/` 数据目录；重新启用后可继续使用原数据
- 归档删除：管理员归档删除普通用户时，后端会先把用户目录移动到 `runtime-data/_system/deleted-users/`，成功后才删除账号记录和 sessions；若归档移动失败，账号与 token 保持原状，避免半删除状态
- 孤儿目录：用户管理接口会对比 `runtime-data/*` 与 `_system/users.json`，管理员可在设置面板将未注册目录归档到 `_system/deleted-users/`；系统不会自动删除或自动收养这些目录
- 启动检查：后端启动时会收紧 `_system/users.json` / `_system/sessions.json` 权限到 `0600`、清理过期 session；若绑定非 loopback 地址但未启用多用户或未设置管理员密码，会拒绝启动（除非显式设置不安全覆盖 `THREADLOOM_ALLOW_PUBLIC_SINGLE_USER=1`）
- 出站请求（site discovery / model 调用）走 `safe_http`：先解析 IP 再连接，每条记录都拒绝 loopback / 私网 / link-local，杜绝 DNS-rebinding

### 公网部署警告

Threadloom 仍是 local-first 应用，不是开箱即用的 SaaS。准备公网访问前必须先在本机完成：

1. 设置 `default-user` 管理员密码
2. 启用多用户模式
3. 通过可信反向代理提供 HTTPS、访问控制与 `/api/auth/login` 限流
4. 确认反向代理没有暴露 `.env*`、`.git`、`config/`、`runtime-data/`、`backend/threadloom.log` 或任何仓库目录浏览

不要直接用单用户模式暴露公网。`THREADLOOM_ALLOW_PUBLIC_SINGLE_USER=1` 只适合已经有外层身份认证 / VPN / 内网网关的受控环境。

### 忘记管理员密码

UI 不提供找回入口。停服后修改 `runtime-data/_system/users.json`：
- 删掉 `default-user` 的 `password_hash` 字段，重新启动后再次走"启用多用户"向导即可重置

普通用户忘记密码：管理员在用户管理里点击 "重置密码"。

## 当前 keeper 结构

当前主链已经是：

1. narrator 生成正文
2. `state_keeper.model` 作为 skeleton keeper 提取最小骨架：
   - `time`
   - `location`
   - `main_event`
   - `onstage_npcs`
   - `immediate_goal`
3. `state_keeper.model` 作为 fill-mode keeper，在骨架上补：
   - `immediate_risks`
   - `carryover_clues`
   - `tracked_objects`
   - `possession_state`
   - `object_visibility`
4. 若 fill-mode keeper 调用失败，降级到 `state_fragment` 基线（skeleton + 上一轮 state + arbiter 合并），不再回退到旧 `state_updater.py` heuristic（`backend/tools/` 仍保留以便重放）

说明：
- `main_event` 目前已比早期版本稳定得多，opening 首轮也能落下有效主事件。
- `immediate_goal` 虽然仍在骨架字段里，但当前稳定性明显低于 `time / location / main_event`，部分回合仍可能回到 `待确认`；它当前更主要影响 `threads / lore trigger / summary`，而不是直接强控 narrator 正文。
- opening-choice 首轮当前会优先走 `skeleton keeper + fill keeper`，而不是直接依赖 heuristic 反提。

当前 keeper 写回保证：
- `tracked_objects / possession_state / object_visibility` 在 fill-mode 合并时按 `object_id` 字典化去重，本轮 payload 在同 id 上覆盖 baseline，避免新数据被旧值掩盖
- `knowledge_scope` 在 fill-mode 合并时与 baseline 增量合并（去重，按角色截顶），避免开局或上一轮未沉淀的 scope 被本轮 keeper 覆盖丢失
- `carryover_signals` 推导出的 `immediate_risks / carryover_clues` 与 baseline 累加去重，再截到 6 条；不会因为本轮信号变少而清空长期持续的风险线索
- narrator 正文若因 `finish_reason=length/error` 或半句停顿被判定为不完整，会自动重试；最终仍失败时本轮不写 assistant history、不递增 turn、不更新 state，历史接口和后续 prompt 也会过滤旧 partial 轮次
- `onstage_npcs / relevant_npcs / scene_entities` 需要通过正向人物证据门槛；地点、标题残片或事件短语不能仅凭 `main_event/location` 反推成人物层

当前 keeper 改进要点：
- skeleton keeper 和 fill keeper 的 LLM prompt 已全面重写，加入字段级质量约束和好坏示例
- skeleton keeper `max_output_tokens` 已从 120 调高到 280，避免中文 JSON 截断
- `local_model_client.py` 增加了截断 JSON 的括号补全 fallback 解析
- heuristic fallback 已从旧关键词匹配重构为基于评分的抽取架构：
  - 统一 `_score_sentence()` 按用途加权
  - `_extract_top_sentences()` 替换旧的 `_extract_key_sentence()`
  - `_summarize_event()` 产出「用户动作→叙事响应」格式
  - 中文自然断点智能截断
  - 阈值过滤（≥2.0）用于 risks/clues
  - 元文本过滤（角色卡字段、AI 自评注、HTML 注释）

## 目录结构

- `backend/`
- `frontend/`
- `config/`
- `prompts/`
- `examples/`
- `character/`
- `memory/`
- `runtime/`
- `doc/`

## 启动

1. 复制配置模板：

```bash
cp config/runtime.example.json config/runtime.json
cp .env.local.example .env.local
```

2. 按你的环境填写：

```bash
config/runtime.json
.env.local
```

`.env.local` 里填真实密钥，`config/*.json` 里只保留 `env:VAR` 引用。

说明：
- `config/runtime.json` 现在主要保留共享内容层与全局运行策略
- 用户自己的站点与模型配置会落到 `runtime-data/<user>/config/`
- 前端设置面板修改的是当前用户自己的站点和模型，不会再把这部分写回共享 `config/`
 - 用户级文件包括：
  - `runtime-data/<user>/config/site.json`
  - `runtime-data/<user>/config/model-runtime.json`
 - 当前前端设置页已经简化为：
   - 站点 URL / API Key / API 类型
   - 获取模型
   - Narrator 模型选择
   - State Keeper 模型选择
 - `temperature` 与 `max_output_tokens` 已回收到共享默认配置：
   - `config/runtime.json -> model_defaults`
 - 高级角色（如 `turn_analyzer / arbiter`）当前不在普通设置页里改，但可以通过 `runtime-data/<user>/config/model-runtime.json -> advanced_models` 手动覆盖；`state_keeper_candidate` 不再单独维护模型，固定继承 State Keeper 模型选择
  - 当前前端会话管理入口：
    - 桌面端：hover 左上角 `用户 · 当前角色卡` 胶囊菜单，弹出最近会话下拉；点击胶囊仍打开“当前世界”设置
    - 移动端：输入区状态栏只保留状态文本；会话切换继续使用左上角 `用户 · 当前角色卡` 胶囊菜单
    - 两个入口都显示当前角色卡下最近更新的最多 5 个会话
    - 下拉/上拉菜单中可直接切换、删除、开始新游戏

3. 准备你自己的内容层：

- `character/`
- `memory/`
- `runtime/persona-seeds/`
- `USER.md`
- `player-profile.json`
- `player-profile.md`

公开仓库同时附带一套最小模板内容：

- `examples/character/`
- `examples/memory/`
- `examples/player-profile.*`
- `examples/USER.md`

如果你暂时还没有准备真实内容，可以先用 `examples/` 跑通最小链路，再逐步替换为自己的本地文件。

当前主角档案建议：

- 用户级基础档案：`runtime-data/<user>/profile/player-profile.base.json`
- 角色卡特化覆盖：`runtime-data/<user>/characters/<character_id>/source/player-profile.override.json`
- 运行时会先加载基础档案，再叠加当前角色卡覆盖
- 玩家档案 JSON 会在后端做宽松归一化：推荐把 `name` / `courtesyName` 放在顶层，但也兼容 `character.name`、`basic.name`、`profile.name`、中文 `名字` / `常用称呼` / `昵称` 等常见写法；归一化只补齐顶层标准字段，不会删除原始嵌套内容
- `USER.md` 现在不再参与 RP narrator 主链，只保留给通用协作备注
- narrator 运行时只消费一份收短后的玩家档案摘要，完整档案仍保留在 JSON 真相源中
- `player-profile.json` / `player-profile.md` 目前保留为兼容副本与可读导出
- narrator prompt 当前采用“强约束层 / 连续性层 / 候选知识层”的分层权重，避免世界书候选压过最近窗口与当前 state

## 角色卡导入

当前推荐把角色卡导入到当前用户/当前角色卡的 source 目录，而不是再手改仓库根下旧 `character/` 目录。

导入命令：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.png
```

或直接导入已提取的 Tavern raw card：

```bash
cd /root/Threadloom
python3 backend/import_character_card.py /path/to/card.raw-card.json
```

导入后当前角色卡 source 目录下会生成：

- `character-data.json`
- `lorebook.json`
- `openings.json`
- `system-npcs.json`
- `import-manifest.json`
- `imported/`
- `assets/`

当前设计原则：

- `character-data.json` 只保留角色核心
- `lorebook.json` 只保留 runtime 可消费的世界知识条目
- `openings.json` 单独保存开局菜单与 bootstrap
- `system-npcs.json` 单独保存系统级 NPC，当前分成：
  - `core`
  - `faction_named`
  - `roster`
- 当前 runtime 默认优先只消费 `core`
- 导入时会尽量剔除 SillyTavern 的前端模板、隐藏脚本、状态栏与关系模板条目
- `assets/` 用于角色卡封面与缩略图

4. 启动：

```bash
cd /root/Threadloom/backend
./start.sh
```

`./start.sh` 会自动加载仓库根目录下的 `.env.local`。

前台启动：

```bash
cd /root/Threadloom/backend
python3 server.py
```

默认监听本机回环地址：

```text
http://127.0.0.1:8765
```

可通过环境变量覆盖监听地址和端口：

```bash
THREADLOOM_HOST=127.0.0.1 THREADLOOM_PORT=8765 ./start.sh
```

如果需要让其他设备访问，不建议直接改成公网监听；应放在可信反向代理后，并补全认证、TLS 与访问控制。

## 文档

建设和设计文档保留在 `doc/` 根目录；已完成计划、旧版本说明和过时审计集中归档到 `doc/archive/`：

- `doc/API.md`
- `doc/ARCHITECTURE.md`
- `doc/BACKEND.md`
- `doc/CONTEXT-FLOW.md`
- `doc/OPERATIONS.md`
- `doc/REVIEW.md`
- `doc/RUNTIME.md`
- `doc/archive/README.md`

## 常用脚本

当前主用入口：

- 启动后端：`backend/start.sh`
- 停止后端：`backend/stop.sh`
- 导入角色卡：`backend/import_character_card.py`
- 导入 SillyTavern 聊天：`backend/import_sillytavern_chat.py`
- 单回合精确回放：`backend/tools/replay_turn_trace.py`
- 从历史重建副本 session：`backend/tools/rebuild_session_from_history.py`

历史迁移 / 实验脚本已清理；当前只保留仍用于调试的 `backend/tools/` 工具。

## 开发与 LSP

当前后端仍按脚本方式运行：开发时从 `backend/` 目录执行 `python3 server.py`，测试时用 `PYTHONPATH=backend` 暴露同级模块。因此 `backend/*.py` 里的 `import user_manager` / `import model_config` 这类导入是运行时契约，不是应立即批量改成包内相对导入的错误。

仓库根目录的 `pyrightconfig.json` 与 `basedpyrightconfig.json` 用于让 Pyright / Basedpyright LSP 匹配这个现实：

- `extraPaths: ["backend"]` 让同级后端模块按脚本入口可解析。
- `reportImplicitRelativeImport` 关闭，避免把当前脚本式导入误报成项目级错误。
- 类型检查保持 `basic`，并暂时关闭 unknown / missing type argument 系列噪音；逐步类型化应按模块单独推进，不和运行方式修复混在一起。

长期如果要把后端改成真正 package 运行（例如 `python3 -m backend.server`），应单独迁移启动脚本、测试入口和所有导入，再收紧这些 LSP 规则。

配置模板：

- `config/runtime.example.json`
- `config/providers.example.json`（仅历史兼容 / 参考）

说明：
- 仓库不包含真实的 `config/runtime.json`
- 仓库不包含真实的 `config/providers.json`
- 发布版本默认保留配置模板，实际端点和 API key 需要本地自行填写
- 仓库默认提交的是 `examples/` 模板内容，而不是你的真实角色卡、memory、session 或用户档案

---

## 📚 相关文档

### 核心文档
- **[doc/audit/SECURITY_AUDIT_2026-04-29.md](doc/audit/SECURITY_AUDIT_2026-04-29.md)** - 安全审计与修复记录
- **[doc/audit/ISOLATION_AND_KEEPER_FIX_2026-04-30.md](doc/audit/ISOLATION_AND_KEEPER_FIX_2026-04-30.md)** - 信息隔离与 keeper 写入路径加固
- **[doc/audit/MULTI_USER_HARDENING_2026-05-01.md](doc/audit/MULTI_USER_HARDENING_2026-05-01.md)** - 多用户后端安全加固（SSRF 防护、登录限速、Cookie/CSRF 边界、per-user 配额）
- **[doc/audit/RUNTIME_GENERICITY_AND_TRACE_2026-05-01.md](doc/audit/RUNTIME_GENERICITY_AND_TRACE_2026-05-01.md)** - runtime 泛化、对象流转与 turn audit 可观察性整理
- **[doc/audit/MULTI_USER_UI_SHIPPED_2026-05-01.md](doc/audit/MULTI_USER_UI_SHIPPED_2026-05-01.md)** - 多用户 UI 上线记录（与 plan 的差异、commit 索引、未做项）
- **[doc/archive/README.md](doc/archive/README.md)** - 已完成计划、旧版本说明、过时/重复审计和历史测试报告的归档索引
