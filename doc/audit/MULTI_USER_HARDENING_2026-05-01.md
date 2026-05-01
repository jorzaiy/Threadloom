# 多用户后端安全加固 — 2026-05-01

## 背景

前端 UI 还没接入，但多用户后端已经成形。在打开多用户开关并暴露给前端之前，对 `backend/user_manager.py` / `backend/server.py` / `backend/model_config.py` / `backend/model_client.py` / `backend/session_lifecycle.py` / `backend/character_manager.py` 做一次定向加固，关闭已识别的 P1（必须修）与 P2（强烈建议修）级别风险。

## 修复清单

### P1 — 必须

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| H1 | `discover_site_models` / `discover_provider_models` / 模型调用都走 `urllib.request.urlopen`，`_validate_remote_base_url` 仅校验配置时的 IP，DNS-rebinding 在实际连接时把 hostname 解析到内网或 loopback 即可绕过 | 新增 `backend/safe_http.py`：`open_safe_connection()` 在请求前 `socket.getaddrinfo` 拿到所有解析地址，**任何一条** 命中私网/loopback/链路本地/multicast/reserved/unspecified 即拒绝，连接到预解析 IP 但保留原 hostname 用于 SNI/证书验证。`model_config.discover_site_models` 与 `model_client._post_json/_post_stream_chat` 全部改走该助手。 | `backend/safe_http.py` (新)、`backend/model_config.py`、`backend/model_client.py` |
| H2 | `login` 没有任何失败计数 / 冷却 | 在 `users.json` 增加 `failed_logins` / `lockout_until` 字段；连续 `LOGIN_FAILURE_LIMIT=5` 次失败后锁 `LOGIN_LOCKOUT_SECONDS=900` 秒；成功登录、`reset_user_password`、`set_admin_password` 重置计数与锁定 | `backend/user_manager.py` |
| H3 | 用户不存在路径直接抛错，不跑 bcrypt；存在用户跑 bcrypt 比对（~200ms）。响应时间差直接暴露用户存在性 | 不存在用户与"密码字段为空且非 default-user 单用户模式"路径都跑一次 dummy bcrypt 比对（预生成的真实 bcrypt 哈希 `_DUMMY_PASSWORD_HASH`），消除时序差 | `backend/user_manager.py` |
| M1 | `resolve_user_from_request` 既接受 Authorization Bearer 也接受 Cookie `session_token=…`。当前没人 `Set-Cookie`，但读路径存在；前端落地后若用 Cookie 存 token，state-changing POST 立刻 CSRF 暴露 | `resolve_user_from_request(headers, *, allow_cookie=True)`；`server.begin_request_user_context` 在 method 为 POST/DELETE 时传 `allow_cookie=False`；`Handler._extract_token`（admin auth 路径）改为 Bearer-only | `backend/user_manager.py`、`backend/server.py` |
| M5 | `set_multi_user_enabled(False)` 清 sessions，但 `True` 不清。bootstrap 阶段（admin 还没设密码）的 default-user 空密码 token 可能跨入多用户态 | `set_multi_user_enabled` 在两个方向都 `_save_sessions({})`，强制所有人重新登录 | `backend/user_manager.py` |

### P2 — 强烈建议

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| M2 | `SESSION_LOCKS: dict[str, threading.Lock]` 只增不减；恶意用户构造 N 个 session_id 即可累积 N 个锁对象 | 改用 `weakref.WeakValueDictionary`。无人持有时由 GC 回收，`with` 块期间局部变量保活，并发场景仍正确 | `backend/server.py` |
| M3 | `validate_token` 仅在被该 token 自身触发时清理过期项，被遗忘的 token 永久驻留 sessions.json | 新增 `_prune_expired_sessions(sessions)`，`_save_sessions` 写盘前调用一次，`login`/`validate_token`/`logout` 自然走过这条路径 | `backend/user_manager.py` |
| M4 | 多用户模式下没有 per-user 配额，单个普通账号可填满磁盘 | `session_lifecycle.MAX_SESSIONS_PER_CHARACTER_FOR_USER=50`、`character_manager.MAX_CHARACTER_CARDS_FOR_USER=10`；仅在 `is_multi_user_enabled() and active_user_id() != DEFAULT_USER_ID` 生效；admin 与单用户模式不受限 | `backend/session_lifecycle.py`、`backend/character_manager.py` |

## 接口契约 (供前端实现参考)

- **认证 token 必须用 Authorization 头** (`Authorization: Bearer <token>`)。
- **Cookie 路径仅供 GET / EventSource** 等无法定制 header 的场景。后端在 GET 上仍然识别 `session_token=<token>`，但 POST/DELETE/PUT 强制忽略 Cookie。
- **失败登录提示信息保持 `'用户不存在或密码错误'` 统一**，前端不要根据返回信息推断用户存在性，也不要把锁定剩余时间显式回填给用户（已经在错误信息里写"账户暂时锁定，请稍后再试"）。
- **多用户切换 toggle 会强制全员重新登录**，前端 UI 应在收到 `multi_user_enabled` 状态变化后清掉本地 token。
- **配额上限**：普通用户每角色卡 ≤50 session、每用户 ≤10 卡；超出时后端返回 400 `INVALID_INPUT`，message 含 `quota exhausted`。前端可以提前在 UI 上 disable 入口。

## 测试

新增：

| 测试 | 覆盖 |
|------|------|
| `tests/test_safe_http.py::SafeHttpResolutionTests` (7 个) | H1 各种私网/loopback/link-local/混合记录拒绝，公网通过，IP 钉死 |
| `test_login_locks_account_after_failure_threshold` | H2 锁定 + 解锁 |
| `test_login_unknown_user_runs_dummy_bcrypt_to_hide_existence` | H3 dummy bcrypt 真的被调用 |
| `test_save_sessions_prunes_expired_entries` | M3 写盘剔除过期 |
| `test_enabling_multi_user_wipes_existing_sessions` | M5 启用即清空 |
| `test_post_request_rejects_cookie_session_token` / `test_get_request_still_accepts_cookie_session_token` | M1 method-aware allow_cookie |
| `test_session_locks_release_when_no_caller_holds_them` | M2 WeakValueDictionary GC |
| `test_session_quota_enforced_for_ordinary_multi_user_user` / `test_character_card_quota_enforced_for_ordinary_multi_user_user` | M4 多用户配额 + admin/单用户豁免 |

执行：

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'
```

结果：115 个测试，本次新增 16 个全部通过，2 个 pre-existing 失败保持不变 (`test_archive_initial_load_defaults_to_safe_mode` 签名漂移、`test_user_profile_route_uses_multi_user_context_before_loading_profile` server 路由级遗留)，与本次修复无关。

## 没做 / 后续

- **L 级条目**（密码强度只查长度、avatar 不验 magic bytes、bcrypt rounds 硬编码、127.0.0.1 监听文档化）：留待 UI 落地后一起做，无即时安全洞。
- **`MULTI_USER_PRODUCT_ENABLED` 仍然为 False**：HTTP 层依旧不暴露 auth/users/multi-user 端点。打开开关与前端落地是同一动作，那时再去掉这一行硬开关。
- **CSRF 双重防护**：当前用 method-aware Cookie + Bearer 默认要求方案就够。如果将来选择 Cookie 存 token，建议补 SameSite=Strict + Secure + HttpOnly；不要用 JS 可读的 cookie。
