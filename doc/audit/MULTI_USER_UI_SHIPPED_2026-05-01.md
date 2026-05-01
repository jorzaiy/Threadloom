# 多用户 UI 上线 — 2026-05-01

> 关联：`doc/MULTI_USER_UI_PLAN.md`、`doc/audit/MULTI_USER_HARDENING_2026-05-01.md`

## 状态

UI 已落地，对应两个 commit：
- `5456a37` — 后端：site/provider 全局化、自助改密端点、`/api/auth/me` 加 role、翻 `MULTI_USER_PRODUCT_ENABLED = True`
- `a79e921` — 前端：登录页、Bearer token 注入、按角色分支的设置面板、多用户启用/关闭向导、用户管理 tab

回归：`PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'` → 124 个测试，2 个 pre-existing failure 不变。

## 与 plan 的差异

七项决策全部按 plan 落地。落地中发现的一项偏差：

- **`model_config.py` 不再用 `from .paths import RUNTIME_DATA_ROOT`，改 `from . import paths as _paths`**
  - 原因：`from X import constant` 在 import 时把常量绑定到本模块；测试 monkey-patch `paths.RUNTIME_DATA_ROOT` 看不到我这份 cached 引用。
  - 改动后 `_global_site_config()` 通过 `_paths.RUNTIME_DATA_ROOT` 动态解引用，测试与生产路径都按预期走 `paths` 模块上的最新值。

## 实际落地的细节

### 后端改动

**`backend/model_config.py`**
- 新增 `_global_site_config()` / `_global_legacy_providers_config()`，返回 `<RUNTIME_DATA_ROOT>/<DEFAULT_USER_ID>/config/site.json` 与 `providers.json`。所有 site/provider 读写都改成调这两个函数。
- 新增 `SiteConfigPermissionError(PermissionError)` 与 `_require_admin(action)`。`update_site_config` / `discover_site_models` / `upsert_provider_config` / `discover_provider_models` 顶部都先 `_require_admin(...)`，普通用户调用直接抛错。
- `_load_site_store_raw()` 与 `load_site_store()` 在普通用户调用时只在内存里返回 seed/normalize 结果，不写盘；admin 调用时维持 seed-and-write 行为。
- 改回 `from . import paths as _paths` 解决 monkey-patch 不生效的问题。

**`backend/user_manager.py`**
- 新增 `change_own_password(uid, old_password, new_password, *, keep_token)`。验证旧密码（包含 dummy bcrypt 时序保护），更新 hash，清空 `failed_logins / lockout_until`，仅保留 `keep_token` 对应的 session。
- `reset_user_password` / `set_admin_password` 在更新密码时也清空锁定状态。

**`backend/server.py`**
- `MULTI_USER_PRODUCT_ENABLED = True`：auth/users/multi-user toggle 端点正式可用。
- `/api/auth/me` 响应增加 `role`（`'admin'` 或 `'user'`）与 `admin_has_password`。
- `/api/auth/change-password` 新路由：Bearer-only 认证 → `validate_token` → `change_own_password(uid, old_pwd, new_pwd, keep_token=token)`。
- `/api/site-config`、`/api/site-models/discover`、`/api/providers`、`/api/providers/discover` 把 `SiteConfigPermissionError` 转成 403 FORBIDDEN。

### 前端改动

**`frontend/index.html`**
- 顶层加 `<div id="loginScreen" hidden>` 全屏登录表单。
- `<div class="app">` 加 `id="appShell"`，便于 JS 切换显示。
- 顶栏右侧加 `#authIndicator` + `#logoutBtn`。
- 设置面板 tab 列表新增 "用户管理"（admin-only）与 "账号" 两个 tab。
- "用户管理" 面板：多用户 toggle + 用户列表（含创建 / 重置密码 / 删除按钮）。
- "账号" 面板：自助改密表单。

**`frontend/styles.css`**
- 新增 `.login-screen / .login-form / .login-field / .login-error` 等登录页样式。
- 新增 `.auth-indicator / .auth-logout-btn` 顶栏标识样式。
- 新增 `.user-list / .user-list-row / .user-role-tag` 用户管理样式。

**`frontend/app.js`**
- `apiJson` 注入 `Authorization: Bearer <localStorage tl_session_token>`，401 自动 `clearAuthToken() + showLoginScreen()`。
- `checkAuth()` 重写：把 `/api/auth/me` 结果写入 `authState`（`userId / role / multiUserEnabled / adminHasPassword`）。
- `init()` 拆成两段：先 `checkAuth`，单用户或已登录直接调 `runMainBoot()`；多用户未登录 → `showLoginScreen()` 等待登录后再走 `runMainBoot()`。
- 新增 `applyRoleBasedUI()`：按 role 隐藏 `.admin-only` 元素、disable 站点写入字段。
- `loginForm` 提交：调 `/api/auth/login` → `setAuthToken` → `runMainBoot`。
- `logoutBtn`：调 `/api/auth/logout` → 清 token → 显示登录页。
- `changePasswordForm`：旧/新/确认 → 调 `/api/auth/change-password`。
- `enableMultiUserWizard / disableMultiUserWizard`：根据 `adminHasPassword` 分支，密码设置 → `/api/multi-user` → `silentReLogin` → `runMainBoot`。失败兜底 `clearAuthToken + showLoginScreen`。
- 用户管理：`loadUsersList` 渲染 `/api/users` 数据，事件委托处理 `data-user-action="reset|delete"`。

## 已知未做项

- **L 级条目**（avatar magic bytes、密码强度、bcrypt 轮数可配）：不在本次范围
- **HttpOnly Cookie + CSRF token 双提交**：当前用 Bearer + method-aware Cookie 拒绝就够；将来若改用 Cookie 存 token 再上 CSRF token
- **忘记密码 UI**：仅文档化"修改 users.json 重启"的 escape hatch
- **审计日志**：暂无 admin 操作记录持久化

## 手动验证清单（用户负责，不在本次自动化覆盖中）

| # | 场景 | 期望 |
|---|------|------|
| 1 | 全新 runtime-data 启动 | 主界面直显，无登录页 |
| 2 | admin 设置 → 启用多用户 → 设置密码 | 主界面无感切到多用户 admin 视图 |
| 3 | admin 创建普通用户 → 退出 → 普通用户登录 | 站点 tab 只读、用户管理 tab 不见 |
| 4 | 普通用户改自己密码 | 当前 session 仍可用，旧密码登录失败 |
| 5 | 5 次错误密码连续登录 | 锁定 15 分钟 |
| 6 | 普通用户开 50+ session | 配额错误提示 |
| 7 | admin 修改 site URL → 普通用户重连 | 看到的是新 URL |
| 8 | curl `/api/site-config POST` 用普通用户 token | 403 |
| 9 | admin 关闭多用户 | 自动重登 → 主界面 |
| 10 | localStorage 清空 token → 任何 API | 跳登录页 |
