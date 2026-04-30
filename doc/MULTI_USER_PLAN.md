# Multi-user Plan

## 目标

本计划定义 Threadloom 从当前单用户本地原型扩展到受控多用户模式的实现范围。多用户模式不提供公开注册；只允许 `default-user` 维护是否启用多用户、创建用户、删除用户、重置用户密码。启用后，普通用户只能访问自己的角色卡、预设、LLM 站点/模型设置、头像、玩家档案和聊天记录。

核心安全原则：`default-user` 是用户管理者，不是租户数据管理员。它可以管理账号生命周期，但不能查看或修改其他用户的角色卡、预设、LLM 配置、聊天记录、玩家档案或 runtime state。

## 非目标

- 不做开放注册、邀请码注册或自助找回密码。
- 不做团队共享角色卡、共享会话或跨用户协作编辑。
- 不做 `default-user` 查看普通用户内容的后台审计能力。
- 不做公网级完整身份系统；如果要公网部署，仍需要反向代理、TLS、额外访问控制和备份策略。

## 当前基础

仓库已有部分多用户骨架，但当前产品面仍关闭：

- `backend/user_manager.py` 已有 bcrypt 密码、token、用户增删、开关字段和 token TTL。
- `backend/server.py` 中 `/api/auth/*`、`/api/users`、`/api/multi-user` 被 `MULTI_USER_PRODUCT_ENABLED = False` 硬关闭。
- `backend/paths.py` 已有 `runtime-data/<user>/` 目录模型，但 `active_user_id()` 目前固定返回 `default-user`。
- 用户级目录已经覆盖配置、预设、角色卡、角色卡 source、session roots、profile 等路径函数。
- 现有大量业务函数通过 `paths.active_user_id()` 间接取当前用户；这是可利用的隔离入口，但需要改成 request-scoped user，而不能继续使用全局固定用户。

### 相关文件清单

- `backend/paths.py`：当前用户、用户目录、角色卡目录、session roots、legacy fallback 的核心入口。
- `backend/user_manager.py`：bcrypt 用户、token session、多用户开关、用户 CRUD、登录/登出。
- `backend/server.py`：HTTP API 总入口；当前多用户路由由 `MULTI_USER_PRODUCT_ENABLED = False` 硬关闭，业务 API 尚无统一 auth gate。
- `backend/model_config.py`：当前用户的 `site.json`、`model-runtime.json`、narrator presets 读写；API key 快照只返回 masked/meta。
- `backend/character_manager.py`：当前用户角色卡列表、切换、导入、删除；active character 存在用户 config 下。
- `backend/runtime_store.py` / `backend/session_lifecycle.py`：当前用户当前角色卡下的 session、history、state、summary、trace、meta 读写。
- `backend/player_profile.py`：用户基础档案、头像、当前角色卡 profile override。
- `backend/character_assets.py`：角色卡 source/assets 与封面解析。
- `backend/import_sillytavern_chat.py`：聊天导入到当前 active user / active character 的 session root。
- `frontend/app.js` / `frontend/index.html`：已有世界、导入、玩家设定、模型连接 UI；只有最小 `/api/auth/me` 检查，没有登录界面、token 管理或用户管理页。

## 目标数据边界

每个用户独立拥有：

- `runtime-data/<user>/config/site.json`
- `runtime-data/<user>/config/model-runtime.json`
- `runtime-data/<user>/presets/*.json`
- `runtime-data/<user>/profile/*`
- `runtime-data/<user>/characters/<character_id>/source/*`
- `runtime-data/<user>/characters/<character_id>/sessions/<session_id>/*`

系统级数据只保存账号元信息和 session token：

- `runtime-data/_system/users.json`
- `runtime-data/_system/sessions.json`

`runtime-data/_template/` 只作为新用户初始化模板；不得在运行期作为跨用户共享可写数据源。

## 架构方案

### 0. 安全和隐私硬约束

多用户实现必须先满足这些约束，再暴露前端用户管理入口。安全性和隐私性优先于功能便利性。

- 认证凭据必须二选一：`Authorization: Bearer` token 或 `HttpOnly` cookie，不允许混用。若使用 cookie，必须启用 `HttpOnly`、`SameSite=Lax/Strict`、按部署条件启用 `Secure`，并为所有写接口提供 CSRF 防护；若使用 bearer token，默认只保存在前端内存中，不使用认证 cookie。
- session token 必须使用高熵随机值；`runtime-data/_system/sessions.json` 不应明文保存可直接使用的 bearer token，应保存 token hash、`user_id`、`created_at`、`last_seen_at`、`expires_at` 等元信息。
- 旧版本若已存在明文 token key，第一次成功校验时必须迁移为 hash key，或在启用多用户前明确清空旧 session；不得长期保留明文 token key。
- 登出、重置密码、删除用户、关闭多用户时，必须撤销受影响用户的 session。登录失败响应不得泄露用户是否存在。
- 密码不得为空或过短；建议最小长度 12。登录必须有按用户和来源地址的节流或退避，失败日志不得记录密码或 token。
- CORS 默认仅允许 same-origin。若未来允许跨源访问，必须使用精确 allowlist；认证 API 不允许 wildcard origin。
- server log、trace、错误响应和前端错误展示不得泄露 token、cookie、密码、API key、Authorization header、其他用户目录路径或其他用户内容。
- 普通用户的 `site.json` 不得引用任意宿主环境变量。若多用户模式继续支持 `env:VAR`，必须改为 allowlist 或仅允许受信任部署显式开启。

### 0.1 Filesystem confinement

所有来自请求、导入文件或前端状态的文件系统标识都视为不可信。

- `user_id`、`character_id`、`session_id`、preset 名、上传文件名和 asset 名必须使用保守校验规则；建议 ID 仅允许 `^[A-Za-z0-9_-]{1,64}$`。
- 禁止路径分隔符、`.` / `..` 段、URL 编码分隔符、控制字符、绝对路径和保留系统名。`_system`、`_template` 只能由内部系统路径使用，不能作为普通用户 ID。
- 每次基于请求输入访问文件前，最终路径必须 `resolve()`，并确认仍在预期的 `runtime-data/<user>/` 或更窄的子目录之下。
- 多用户模式必须拒绝 symlink escape；上传或解包资产不得创建或跟随攻击者控制的 symlink。
- 删除 runtime 数据前必须确认目标严格位于对应用户目录下，且不是 `_system`、`_template`、仓库根或 symlink escape。
- `_system/users.json` 与 `_system/sessions.json` 必须原子写入，并使用进程级锁保护并发更新；认证状态损坏时，多用户模式必须 fail closed，而不是回退到免登录。

### 0.2 Migration and bootstrap

启用多用户前必须先完成或确认单用户数据迁移。

- 现有单用户数据必须归属到 canonical `default-user`。canonical 账号 ID 只有 `default-user`；`default_user` 只能作为旧显示文本或 legacy 文档引用，不能成为另一套身份目录。
- 启用多用户前必须设置 `default-user` 密码；否则启用接口返回明确错误，前端引导设置密码。
- 多用户启用后，legacy sessions、profile、preset、character source/assets、LLM config 和 import output 不得再作为用户数据 fallback。仅允许共享只读模板和全局 runtime defaults。
- 关闭多用户只恢复未登录访问 `default-user` 数据，不合并、不展示、也不授权访问普通用户目录。

### 0.3 Admin boundary

`default-user` 的管理能力只限账号生命周期，不包含租户数据访问能力。

- 业务 API 在多用户模式下不得接受目标 `user_id` 参数；业务数据访问的唯一身份来源是 request-scoped authenticated user。
- 管理 API 只能对目标用户执行 create、delete account、reset password、revoke sessions、可选删除 runtime directory 等账号生命周期操作。
- 本阶段不提供 impersonate user、view user config、download user data、admin repair user data 或跨用户后台审计接口。

### 0.4 Static assets, uploads, and cache privacy

- 用户资产只能通过绑定当前 authenticated user 的 handler 返回；不得把 `runtime-data/` 作为通用静态目录暴露。
- `/user-avatar`、`/character-cover` 等资产接口必须认证并绑定当前用户，即使请求参数选择了非 active character，也只能在当前用户目录中解析。
- 用户数据和用户资产响应必须使用隐私友好的 cache header，优先 `Cache-Control: no-store`；若因体验需要缓存，只能使用 `private, no-cache`，不能让共享缓存保存用户内容。
- 所有 upload/import endpoint 必须限制 request body、文件数、解包后总大小、文件名长度、允许扩展名/类型；必须拒绝 archive traversal、symlink、绝对路径和 decompression bomb。

### 0.5 Operational semantics

- 删除账号默认只禁用登录并撤销 session，保留 `runtime-data/<user>/` 以避免误删。删除 runtime 数据必须是单独显式动作，带二次确认和路径 confinement 验证。
- 重新创建曾删除的 `user_id` 时，必须明确是重新关联旧目录还是拒绝直到操作员处理，不能静默把旧隐私数据交给新人。
- password reset 撤销该用户所有 session；delete user 立即撤销 session 并阻止新请求。in-flight request 要么在原用户目录内安全完成，要么在写入前中止。
- 当前 `_system/users.json` 与 `_system/sessions.json` 的事务锁是单进程内锁，适配当前 `ThreadingHTTPServer` 本地部署模型。若未来改成 gunicorn/uwsgi/多进程或多实例部署，必须升级为 OS/file lock 或外部事务存储。
- CLI/离线工具默认视为 operator-only。多用户启用后，涉及读取或生成 session/trace/history 的工具必须显式指定 source/target user 或保持只处理 `default-user`，并在文档中说明。

### 1. Request-scoped user context

当前最大缺口是 `active_user_id()` 固定返回 `default-user`。实现时需要引入 request-scoped current user：

- 在每个 HTTP 请求入口解析 token，得到 `request_user_id`。
- 将 `request_user_id` 设置到上下文变量（建议 Python `contextvars.ContextVar`），让 `paths.active_user_id()` 从上下文读取。
- 请求结束后重置上下文，避免 `ThreadingHTTPServer` 线程复用导致用户串线。
- 对后台/CLI 路径保留默认 `default-user`，但 CLI 如导入工具后续可显式传 user。

验收：两个用户并发请求时，`user_config_root()`、`character_root()`、`current_sessions_root()` 必须指向各自目录。

实现注意：所有 `do_GET` / `do_POST` / `do_DELETE` 都需要在进入业务分支前统一设置上下文；异常、早返回和客户端断连路径也必须 reset。不要在单个业务函数里临时传 user_id 拼路径，否则会形成两套路径模型。

### 2. Auth gate and role model

多用户启用后，除静态文件、健康检查、登录接口外，所有 API 都必须要求有效 token。角色分两类：

- `default-user`：可调用用户管理接口和切换多用户开关；不能通过管理接口读取/写入其他用户业务数据。
- 普通用户：只能调用自己的业务接口，不能管理用户、不能切换多用户开关。

多用户关闭时维持当前单用户兼容行为：请求默认落到 `default-user`，业务 API 不要求登录。

建议建立集中式路由分类：`public`（静态文件、健康检查、登录）、`user`（业务 API）、`default-user-admin`（用户管理和多用户开关）。不要把权限判断散落在每个 route 分支里，否则后续新增 API 容易漏 gate。

### 3. User management API

需要补齐并明确 API 语义：

- `GET /api/auth/me`：返回当前登录用户、是否启用多用户、是否为 `default-user`。
- `POST /api/auth/login`：返回 token，并建议前端只存内存或使用受控 cookie；若使用 cookie，需要 `HttpOnly`、`SameSite=Lax/Strict`、`Secure` 条件化。
- `POST /api/auth/logout`：删除当前 token。
- `GET /api/users`：仅 `default-user` 可查看账号列表；只返回 `user_id / role / created_at / has_password`，不返回任何用户业务配置。
- `POST /api/users`：支持 `create`、`delete`、`reset_password`、`set_admin_password`。
- `POST /api/multi-user`：仅 `default-user` 可启停；启用前必须确保 `default-user` 已设置密码。

删除用户时只删除账号与 token；是否删除该用户 runtime 数据建议做显式参数，默认保留数据目录以降低误删风险。

### 4. Frontend session and admin UI

前端需要新增登录态和用户管理入口：

- 未登录且多用户启用时显示登录界面。
- 登录后普通用户只看到自己的世界、角色卡、模型连接、预设、聊天记录。
- `default-user` 额外看到“用户管理”页：启用/关闭多用户、新增用户、删除用户、重置密码。
- 用户管理页不得出现“代入用户查看配置/聊天”的入口。
- 所有 API 请求统一带 token；401 时回到登录界面并清理本地 token。

### 5. Data isolation audit

实现时需要逐项核查这些路径和函数是否完全走 request user：

- `model_config.py`：site/model runtime/presets 均应按当前用户读写。
- `character_manager.py`：角色卡列表、选择、删除、导入必须按当前用户目录。
- `runtime_store.py` / `session_lifecycle.py`：session list/history/state/new/delete 必须按当前用户当前角色卡目录。
- `player_profile.py`：profile/avatar/override 必须按当前用户与当前角色卡目录。
- `opening.py` / `context_builder.py` / `handler_message.py`：上下文装配不得回退读取其他用户目录。
- `/character-cover`、`/user-avatar`：静态资产响应必须只服务当前请求用户的资产。

重点审计 legacy fallback：`paths.session_roots()` 当前包含 legacy `/root/Threadloom/sessions`，`resolve_layered_source()` 在用户/角色路径不存在时会回退共享 legacy 路径。多用户启用后应明确策略：session 不应跨用户回退；共享 `config/runtime.json` 和模板内容可只读共享；角色卡、玩家档案、预设、聊天记录、头像、LLM 配置不得回退到其他用户数据。

## 工作量估算

按当前代码结构，建议拆成 5 个阶段：

1. 后端用户上下文与 auth gate：1.5-2 天。
2. 用户管理 API 语义补齐与测试：1 天。
3. 路径隔离全链审计和修补：2-3 天。
4. 前端登录态与用户管理 UI：2-3 天。
5. 多用户 E2E 回归、并发隔离测试、文档更新：1.5-2 天。

总计约 8-11 人日。若要求 cookie 登录、CSRF 防护、远程部署硬化和更完整测试矩阵，建议预留 12-15 人日。

## 风险点和难点

- **全局 active user 风险**：当前 `active_user_id()` 是全局固定值。若改成普通全局变量，在多线程 server 下会串用户；必须使用 request-scoped context，并在请求结束 reset。
- **隐式路径回退风险**：`resolve_layered_source()` 仍可能回退到共享 legacy 目录。多用户启用时需要明确哪些共享内容仍允许只读 fallback，哪些必须用户隔离。
- **default-user 权限边界**：用户管理接口很容易顺手做成“管理员可查看所有用户配置”。本需求明确禁止，设计和测试都要把它当成硬约束。
- **会话 ID 碰撞与越权**：即使两个用户使用同名 session，也必须落在各自目录；任何直接按 session_id 查 legacy `sessions/` 的路径都要审查。
- **角色卡封面和头像泄露**：图片接口看似静态，但如果用 query 参数选择角色卡，必须绑定当前用户目录，不能允许猜测其他用户 character_id 读取资产。
- **LLM API key 隐私**：`default-user` 不能读取普通用户 `site.json`；API 返回也只能返回 masked/meta，不返回明文 key。
- **删除用户语义**：删除账号是否删除 runtime 数据需要谨慎。默认保留目录更安全，但 UI 要说清楚；若支持删除数据，需要二次确认并验证路径 confinement。
- **测试成本高**：需要构造至少 `default-user + user-a + user-b` 三用户，验证配置、角色卡、预设、聊天记录、头像、session 同名隔离和管理权限拒绝。
- **前端状态残留风险**：当前前端已有较多全局状态（当前 session、角色卡、模型配置、玩家档案、头像 URL）。切换登录用户时必须统一清空并重载，否则可能在 UI 上短暂显示上一个用户的数据。
- **CLI/工具默认用户风险**：导入角色卡、导入聊天、replay/rebuild 等工具当前默认走 `default-user`。这对兼容有利，但多用户实现后需要文档化，并为需要的工具补显式 `--user`。

## 建议验收标准

- 多用户关闭：现有单用户流程不需要登录，原回归测试通过。
- 多用户启用：未登录访问业务 API 返回 401；登录后只能看到当前用户数据。
- `default-user` 可创建、删除、重置用户密码、启停多用户；不能读取或修改其他用户业务配置和聊天数据。
- `user-a` 与 `user-b` 使用同名角色卡、同名 session 时，历史、state、trace、角色卡封面和 LLM 设置互不影响。
- 普通用户访问 `/api/users`、`/api/multi-user` 返回 403。
- 切换登录用户后，前端必须刷新角色卡、session、profile、model config、preset 列表，不残留前一用户 UI 状态。
- 关闭多用户后，只能免登录访问 `default-user` 数据，不能读取或合并普通用户目录。
- token 过期、logout、password reset、delete user 后，旧 token 均不能继续访问业务 API。
- 未登录、登出后、跨用户直接请求头像/角色卡封面均不能读取其他用户资产。
- server log、trace 和错误响应不包含 token、cookie、密码、API key 或其他用户内容。

## 建议测试矩阵

- 单用户兼容：多用户关闭时，不登录仍能完成 health、sessions、new-game、message、history、site/model config 基础流程。
- 登录与权限：未登录访问业务 API 为 401；普通用户访问 `/api/users` / `/api/multi-user` 为 403；`default-user` 可管理账号但无“查看他人数据”接口。
- 同名隔离：`user-a` 与 `user-b` 创建同名 session、同名角色卡、同名 preset，验证读写互不影响。
- 配置隐私：`user-a` 修改 LLM site/API key/model 后，`user-b` 和 `default-user` 的 config snapshot 不出现该配置。
- 资产隐私：头像、角色卡封面、导入卡 assets 只能由当前登录用户读取。
- 上下文隐私：发送消息后生成的 history/state/summary/trace/meta 都只落在当前用户目录。
- 并发隔离：两个用户并发发送消息时，`active_user_id()` 上下文不串线。
- 路径攻击：`../x`、URL encoded slash、绝对路径、`_system`、`_template`、控制字符、symlink escape 均被拒绝。
- 认证撤销：logout、token expiry、password reset、delete user 后旧 session 失效。
- CSRF/CORS：若使用 cookie auth，写接口必须拒绝缺失 CSRF 或非法 origin；若使用 bearer auth，认证 API 仍不得接受 wildcard authenticated CORS。
- 上传滥用：超大 body、过多文件、非法扩展名、archive traversal、symlink、decompression bomb 均被拒绝。
- 前端 stale state：用户切换或 401 后，旧请求 late response 不得渲染到新用户界面。
- 日志脱敏：测试或审计确认 token、password、API key 不出现在 server log、trace 和前端错误中。
