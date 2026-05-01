# 多用户 UI 实施计划

> 起草日期：2026-05-01
> 状态：待执行
> 关联：`doc/audit/MULTI_USER_HARDENING_2026-05-01.md`

## 1. 目标与边界

把已经成熟的多用户后端打开给前端使用。引入登录页、按角色分支的设置面板、用户管理界面、以及一个把单用户实例无感升级为多用户的向导。

**非目标**：忘记密码自助恢复、邮件验证、SSO/OIDC、双因素认证、租户隔离层级（单一 admin 模型）。

## 2. 七项关键决策（已确认）

| 决策 | 取值 |
|------|------|
| Q1 站点配置全局化 | 后端真全局：`load_site_store / update_site_config / discover_site_models` 都强制读写 `runtime-data/default-user/config/site.json`；写入要求 `active_user_id() == DEFAULT_USER_ID` |
| Q2 备用 provider | 同 Q1 处理。`upsert_provider_config / delete_provider_config / discover_provider_models` 都走全局 + admin-only 写 |
| Q3 普通用户自助改密 | 新增 `POST /api/auth/change-password`，需 Bearer + 旧密码验证 |
| Q4 token 存储 | `localStorage['tl_session_token']`，与 7d TTL 对齐；apiJson 注入 `Authorization: Bearer` |
| Q5 启用多用户后的 admin 当前 session | 静默重登：拿向导中刚输入的密码立刻 `/api/auth/login` 拿新 token；失败兜底跳登录页 |
| Q6 `MULTI_USER_PRODUCT_ENABLED` 硬开关 | 翻为 True，auth 端点正式上线 |
| Q7 启用按钮可见性 | 总是可见。点击后视当前 admin 是否有密码弹不同向导（设密码 → 启用 / 仅确认 → 启用） |

## 3. 用户流程

### 3.1 单用户模式（默认）
- `/api/auth/me` 返回 `{user_id: 'default-user', role: 'admin', multi_user_enabled: false}`
- 不显示登录页；与当前体验一致
- 设置面板：保留所有原有 tab；新增"管理员密码"区（如未设置则提示"启用多用户前需要设置"）；新增"启用多用户模式"按钮

### 3.2 单用户 → 多用户切换向导
**Admin 当前无密码：**
1. 点 "启用多用户模式" → 模态框 "设置管理员密码"（new password + confirm）
2. 前端：`POST /api/users {action: 'set_admin_password', password}` → 200
3. 前端：`POST /api/multi-user {enabled: true}` → 200，后端清空所有 sessions
4. 前端：内存里持有刚输入的密码，立刻 `POST /api/auth/login {user_id: 'default-user', password}` → 拿新 token → 存 localStorage
5. 重新加载主界面（多用户 admin 视图）；密码字段从内存清掉

**Admin 已有密码：**
1. 点 "启用多用户模式" → 模态框 "请输入管理员密码以确认"
2. 前端：`POST /api/multi-user {enabled: true}` → 200
3. 前端：用刚输入的密码静默 re-login → 拿新 token

**任一步失败：**
- 密码不合法 / 已被其他人占用 → 显示后端错误，停在向导里
- enable 调用失败 → 显示错误，向导可重试
- 静默 re-login 失败 → 跳登录页（兜底）

### 3.3 多用户 admin 视图
- 启动 → `/api/auth/me` → 没 token → 登录页
- 登录成功后：与当前 UI 一致 + 多用户专属菜单
  - 用户管理 tab
  - 多用户模式 toggle（"关闭多用户模式" 入口）
  - 站点 / provider tab：可写
  - 顶栏右侧：当前用户名 + 登出按钮

### 3.4 多用户普通用户视图
- 登录页 → 登录成功
- 与 admin 视图差别：
  - 站点 tab：只读，apiKey mask（继续走后端 `api_key_masked` 字段）
  - Provider tab：只读
  - 没有用户管理 tab
  - 没有多用户模式 toggle
  - "修改我的密码" 按钮（admin 也有，调一样的端点）
- 模型分配 / Preset：可写（per-user）

### 3.5 多用户 → 单用户切换
- Admin 在多用户 toggle 处点 "关闭"
- 模态框 "确认关闭？所有其他用户将被注销，他们的 sessions 与 token 全部清空"
- 前端：`POST /api/multi-user {enabled: false}`
- 后端清空所有 sessions（M5）
- Admin 当前 token 也失效 → 静默 re-login（用刚输入的确认密码 / 或 admin 仍有的密码）→ 重载

### 3.6 锁定 / 配额错误展示
- 登录失败连续 5 次 → 后端返回 `'账户暂时锁定，请稍后再试'`，前端登录页直接展示
- 普通用户超 50 sessions / 10 cards → 后端 400 `quota exhausted`，前端在对应入口附近 toast / inline message
- 既有 `apiJson` 错误处理已经够用，UI 仅需把错误消息亮出来

## 4. 后端改动

### 4.1 站点配置全局化（Q1）
**文件**：`backend/model_config.py`

替换：
- `_user_site_config()` 改名为 `_global_site_config_path()`，返回 `RUNTIME_DATA_ROOT / DEFAULT_USER_ID / 'config' / 'site.json'`
- 所有内部使用 `_user_site_config()` 的地方都换成全局路径
- `_legacy_user_providers_config()` 改名 `_global_legacy_providers_config()`，同上

注意：`is_multi_user_enabled()` 已经读 default-user 的 site.json，与改动天然一致；`load_site_store` 在多用户模式下若被普通用户触发，因为读取的是 admin 的 site.json，会自动从 admin 处复制 site 配置。

写入鉴权：
- `update_site_config(payload)`：在函数顶部 `if active_user_id() != DEFAULT_USER_ID: raise PermissionError('only admin can configure site')`
- `discover_site_models()`：同上
- `upsert_provider_config / delete_provider_config / discover_provider_models`：同上

API 层：`backend/server.py` 的 `/api/site-config POST`、`/api/site-models/discover POST`、`/api/providers POST/DELETE`、`/api/providers/discover POST` 把 `PermissionError` 转 403 响应。

读路径不变：`/api/site-config GET`、`/api/providers GET` 所有用户都能读，只是返回的内容是 admin 的全局配置 + masked apiKey。

### 4.2 自助改密端点（Q3）
**文件**：`backend/user_manager.py` + `backend/server.py`

```python
def change_own_password(user_id: str, old_password: str, new_password: str) -> None:
    uid = _validate_user_id(user_id)
    pwd = _validate_password(new_password)
    with _SYSTEM_FILE_LOCK:
        users = _load_users()
        user = users.get(uid)
        if not isinstance(user, dict):
            raise ValueError('用户不存在或密码错误')
        # 走与 login 相同的 dummy bcrypt 路径，避免时序差
        pw_hash = user.get('password_hash', '')
        if not pw_hash:
            # default-user 无密码时允许空 old_password（仅单用户模式）
            if uid == DEFAULT_USER_ID and not old_password and not is_multi_user_enabled():
                pass
            else:
                _verify_password(old_password, _DUMMY_PASSWORD_HASH)
                raise ValueError('用户不存在或密码错误')
        else:
            if not _verify_password(old_password, pw_hash):
                raise ValueError('用户不存在或密码错误')
        user['password_hash'] = _hash_password(pwd)
        user['failed_logins'] = 0
        user['lockout_until'] = 0
        users[uid] = user
        _save_users(users)
        # 仅当前 token 保留，其他 token 全部失效（防止旧设备继续用旧密码登录后还活着）
```

注意：与 `reset_user_password` 不同，这里**保留当前调用方的 token**。需要 server 层把当前 token 传进来 → 写入时跳过该 token：

```python
def change_own_password(user_id, old_password, new_password, *, keep_token: str | None = None) -> None:
    ...
    sessions = _load_sessions()
    keep_key = _hash_token(keep_token) if keep_token else None
    sessions = {k: v for k, v in sessions.items() if v.get('user_id') != uid or k == keep_key}
    _save_sessions(sessions)
```

API：
```python
if parsed.path == '/api/auth/change-password':
    if not MULTI_USER_PRODUCT_ENABLED:
        return self._send(403, _experimental_disabled_payload('change-password'))
    token = self._extract_token()  # Bearer-only
    uid = validate_token(token)
    if not uid:
        return self._send(401, {'error': {...}})
    old_pwd = self._payload_string(payload, 'old_password', required=False) or ''
    new_pwd = self._payload_string(payload, 'new_password')
    if new_pwd is None:
        return
    try:
        change_own_password(uid, old_pwd, new_pwd, keep_token=token)
    except ValueError as err:
        return self._invalid_input(str(err))
    return self._send(200, {'ok': True})
```

`/api/auth/change-password` 加入 `_public_paths_for_method('POST')` 是错的—它是 state-changing，**不公开**。但需要 Bearer 通过 `begin_request_user_context`（POST 路径只接受 Bearer）。

### 4.3 `/api/auth/me` 加 role
**文件**：`backend/server.py`

```python
if parsed.path == '/api/auth/me':
    uid = resolve_user_from_request(dict(self.headers))  # GET 允许 cookie
    if is_multi_user_enabled() and uid is None:
        return self._send(401, {'error': {'code': 'AUTH_REQUIRED', ...}})
    role = 'admin' if uid == DEFAULT_USER_ID else 'user'
    return self._send(200, {
        'user_id': uid or '',
        'role': role,
        'multi_user_enabled': is_multi_user_enabled(),
    })
```

### 4.4 `MULTI_USER_PRODUCT_ENABLED = True`（Q6）
**文件**：`backend/server.py`

把 `MULTI_USER_PRODUCT_ENABLED = False` 改为 `True`。审计文档里 P3 的 deferred 项部分（Cookie 属性指南、avatar magic bytes、密码强度）依然不做，仅打开 auth 端点。

### 4.5 测试增量
**文件**：`tests/test_multi_user_foundation.py`

- `test_site_config_global_path_used_for_all_users`：admin 写 site，普通用户读到的是 admin 的
- `test_site_config_write_rejected_for_ordinary_user`：非 admin 调 `update_site_config` 抛
- `test_provider_config_write_rejected_for_ordinary_user`
- `test_change_own_password_keeps_current_token`：改密后当前 token 仍可用，其他 token 失效
- `test_change_own_password_with_wrong_old_password_runs_dummy_bcrypt`：时序一致
- `test_auth_me_returns_role_for_admin_and_user`

## 5. 前端改动

### 5.1 `apiJson` 注入 token
**文件**：`frontend/app.js`

```js
const TOKEN_KEY = 'tl_session_token';

function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

async function apiJson(url, options = {}) {
  if (options.body && !options.headers?.['Content-Type']) {
    options.headers = { ...options.headers, 'Content-Type': 'application/json' };
  }
  const token = getToken();
  if (token) {
    options.headers = { ...options.headers, 'Authorization': `Bearer ${token}` };
  }
  const res = await fetch(url, options);
  if (res.status === 401) {
    clearToken();
    showLoginScreen();  // 不抛错，避免每个调用方都要 catch
    throw new Error('请先登录');
  }
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message || `request failed: ${url}`);
  }
  return data;
}
```

### 5.2 启动序列
**文件**：`frontend/app.js`（替换当前 entrypoint）

```js
async function boot() {
  let me;
  try {
    me = await apiJson('/api/auth/me');
  } catch (err) {
    showLoginScreen();
    return;
  }
  applyAuthState(me);
}

function applyAuthState(me) {
  window._me = me;
  if (!me.multi_user_enabled) {
    hideLoginScreen();
    showMainApp();
    return;
  }
  if (!me.user_id) {
    showLoginScreen();
    return;
  }
  hideLoginScreen();
  showMainApp();
  applyRoleBasedUI(me.role);
}
```

### 5.3 登录页
**文件**：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`

新增 `<div id="loginScreen" hidden>...`，包含用户名输入、密码输入、错误提示区、登录按钮。`showLoginScreen / hideLoginScreen` 控制 `hidden` 属性。

```js
async function doLogin(userId, password) {
  loginErrorEl.textContent = '';
  try {
    const data = await apiJson('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, password }),
    });
    setToken(data.token);
    const me = await apiJson('/api/auth/me');
    applyAuthState(me);
  } catch (err) {
    loginErrorEl.textContent = err.message;
  }
}
```

### 5.4 退出登录按钮
- 多用户模式可见，单用户模式隐藏
- 调 `POST /api/auth/logout` → 清 token → `showLoginScreen()`

### 5.5 设置面板按角色分支
**文件**：`frontend/app.js`、`frontend/index.html`

新增 `applyRoleBasedUI(role)`：
- `role === 'user'`：
  - 站点 tab `<input>` 全部加 `disabled`，`apiKey` 显示 mask 不可改
  - 隐藏 "用户管理" tab、"多用户模式" toggle 区
  - 隐藏 "重新发现模型" 按钮
  - 显示 "修改我的密码" 按钮
- `role === 'admin'`：
  - 全部可见，含用户管理与多用户 toggle

`applyAuthState` 在 `multi_user_enabled === false` 时把上述限制全部解除（admin 单用户态享有全部权限）。

### 5.6 修改密码 modal
- 旧密码 + 新密码 + 确认
- `POST /api/auth/change-password {old_password, new_password}`
- 成功后关闭 modal，token 不变

### 5.7 启用多用户向导
**Admin 无密码**（query `me.role === 'admin'` && `/api/users` GET 返回 `users[default-user].has_password === false`）：
1. 点击 "启用多用户" → 弹"设置管理员密码" modal
2. 提交 → `POST /api/users {action: 'set_admin_password', password}`
3. 成功 → 同一向导继续 → `POST /api/multi-user {enabled: true}`
4. 成功 → 内存中保留 password → `POST /api/auth/login {user_id: 'default-user', password}` → 存 token → 重载 `applyAuthState`

**Admin 已有密码**：
1. 点击 → 弹"输入管理员密码确认" modal
2. 提交 → 直接 `POST /api/multi-user {enabled: true}`
3. 静默 re-login（用刚输入的密码）→ 重载

**关闭多用户**（admin in multi-user mode）：
1. 点击 toggle → 弹"再次输入密码确认" modal
2. `POST /api/multi-user {enabled: false}`
3. 静默 re-login → `applyAuthState` 检测到 `multi_user_enabled === false` → 主界面

### 5.8 用户管理 tab（admin only）
- `GET /api/users` 列表
- 创建：`POST /api/users {action: 'create', user_id, password}`
- 重置密码：`POST /api/users {action: 'reset_password', user_id, password}`
- 删除：`POST /api/users {action: 'delete', user_id}`
- 显示每个用户的 `has_password`、`created_at`，不显示 hash

## 6. 提交策略

| Commit | 范围 |
|--------|------|
| 1. backend | site/provider 全局化 + admin-only 写鉴权 + change-password + auth/me 加 role + 翻 MULTI_USER_PRODUCT_ENABLED + 后端测试 |
| 2. frontend | apiJson 注入 + 启动序列 + 登录页 + 退出 + 角色分支 + 改密 modal + 启用向导 + 用户管理 tab |
| 3. doc | 更新 README、`doc/audit/` 增量记录、操作手册 |

如果 frontend 太大可拆 2a (auth+登录) / 2b (settings 重组+用户管理)。

## 7. 测试与验证

### 7.1 单元 / 集成（自动化）
- 后端：见 4.5
- 前端：纯 vanilla JS 没有 e2e 框架；本次不引入

### 7.2 手动验证清单
1. 全新 runtime-data，单用户模式启动 → 主界面直显，无登录页 ✅
2. Admin 在设置 → 启用多用户 → 设置密码 → 主界面无感切到多用户 admin 视图 ✅
3. 创建普通用户 → 退出登录 → 普通用户登录 → 站点 tab 只读、用户管理 tab 不存在 ✅
4. 普通用户改自己的密码 → 旧密码错误时提示一致；改完仍能用当前 session ✅
5. 普通用户 5 次错误密码登录 → 锁定 15 分钟 ✅
6. 普通用户开 50 个 session 之后再点新游戏 → 配额错误提示 ✅
7. Admin 修改 site URL → 普通用户重连后看到的也是新 URL ✅
8. 普通用户 curl `/api/site-config POST` → 403 ✅
9. Admin 关闭多用户 → 自动重登 → 主界面回到单用户态 ✅
10. localStorage 清空 token → 任何 API 调用 → 跳登录页 ✅

## 8. 风险与未覆盖项

- **忘记密码**：admin 自己忘了，只能停服 + 手动改 `runtime-data/_system/users.json` + 重启。文档里写明这个 escape hatch。普通用户忘了走 admin reset。
- **CSRF / Cookie**：当前后端 POST 拒绝 Cookie auth。前端只用 localStorage + Bearer header，浏览器不会自动附 Cookie。XSS 仍是潜在威胁，CSP 已经收紧；后续如果要彻底防 token 泄露，方案是改 HttpOnly cookie + 双提交 CSRF token，本次不做。
- **`MULTI_USER_PRODUCT_ENABLED` 翻 True 后单用户体验**：单用户态下登录端点也响应。如果有人 curl `/api/auth/login` 用空密码 + default-user，且 admin 仍未设密码，会成功拿到 token。本次的 H2 / H3 / 锁定保护对此场景不适用（empty password 路径在 single-user 模式合法）。建议文档强调"单用户模式只在受信任本机回环使用"。
- **静默重登失败的并发竞态**：admin 启用多用户后 sessions 全清，立刻 login 重新拿 token。如果在 enable → login 之间另一个 tab 先发了请求，会 401。前端可以接受这一过渡态，让 401 自动跳登录。

## 9. 后续（不在本次范围）

- L 级条目：avatar magic bytes / bcrypt rounds 可配 / 密码强度规则细化
- 用户配额管理 UI（admin 可调整每个用户的上限）
- 操作审计日志（用户登录、admin 操作记录）
- 忘记密码的 admin reset 走邮件 / 命令行 tool
