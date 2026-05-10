# Threadloom 代码检查报告

**日期：** 2026-05-10  
**范围：** 后端 Python 代码、前端 JS/HTML/CSS、工程配置  
**方法：** 静态分析（pyright basic）、grep 模式匹配、pytest 全量运行

---

## 一、工程管理问题

### 1. 无依赖管理文件

没有 `requirements.txt`、`pyproject.toml` 或 `Pipfile`。项目依赖 bcrypt、requests、Pillow、jieba 等第三方包，但没有任何地方声明版本约束，新环境部署需要靠猜。

### 2. 测试失败（3 failed + 3 errors）

- `test_llama_quality` — `ZeroDivisionError: division by zero`（逻辑 bug）
- `test_multi_user_foundation` 中 2 个测试 — 全量运行时因测试间状态污染而失败（单独运行通过），说明测试隔离不足
- `test_model_comparison`、`test_model_compare_simple`、`test_skeleton_impact` — fixture `session_id` 未定义，测试本身就是坏的

### 3. 10 个 pyright 类型错误（basic 模式）

| 文件 | 行 | 问题 |
|------|-----|------|
| `model_client.py` | 152 | 对可能为 None 的值调用 `.strip()` |
| `safe_http.py` | 61, 63, 79 | 类型不匹配；访问不存在的属性 `_context` |
| `card_importer.py` | 295 | 返回值可能为 None 但声明返回 str |
| `opening.py` | 21 | 返回值可能为 None 但声明返回 str |
| `tools/rebuild_session_from_history.py` | 246 | 参数可能为 None |
| `test_card_importer.py` | 592 | 参数类型不匹配 |
| `test_full_regression.py` | 192-193 | 调用了不存在的参数名 |

---

## 二、后端代码问题

### 4. 大量异常吞没

34 个文件中共 114 处 `except Exception:` 或 `except BaseException:`，很多没有 log 也没有 re-raise。高频文件：

- `runtime_store.py` — 13 处
- `state_keeper.py` — 12 处
- `server.py` — 9 处
- `handler_message.py` — 6 处
- `tools/rebuild_session_from_history.py` — 6 处

这会导致 bug 被静默掩盖，排查困难。

### 5. 非原子文件写入

`card_importer.py`、`player_profile.py`、`model_config.py`、`character_manager.py`、`paths.py`、`lorebook_distiller.py` 等至少 10 处使用 `path.write_text()` / `path.write_bytes()` 直接写入。如果进程在写入中途崩溃或断电，文件会损坏。

核心的 `runtime_store.py` 和 `user_manager.py` 用了原子写入（`os.fdopen` + `os.replace`），但其他模块没有统一使用。

### 6. ThreadingHTTPServer + 文件竞态

服务器使用多线程处理请求（`ThreadingHTTPServer`），但只有 `server.py` 中的 `SESSION_LOCKS` 保护了 session 级操作。其他模块（如 `model_config.py`、`player_profile.py`）的文件读写没有锁保护，并发请求可能导致数据竞争。

### 7. 单文件过大

| 文件 | 行数 |
|------|------|
| `state_bridge.py` | 2348 |
| `state_updater.py` | 2108 |
| `card_importer.py` | 1677 |
| `state_keeper.py` | 1621 |
| `server.py` | 1260 |
| `handler_message.py` | 1180 |
| `context_builder.py` | 1130 |

---

## 三、前端代码问题

### 8. Token 存储在 localStorage

`login.js` 和 `app.js` 将 session token 存入 `localStorage`。虽然后端对 POST 请求强制要求 Bearer header（防 CSRF），但 localStorage 对 XSS 攻击没有防护。后端已设置 HttpOnly cookie，但前端同时又在 localStorage 存了一份 token。

### 9. 事件监听器无清理

68 个 `addEventListener`，0 个 `removeEventListener`。对于动态创建/销毁的 DOM 元素绑定的事件，会造成内存泄漏。

### 10. innerHTML 拼接风险

共 19 处 innerHTML 赋值。`renderMarkdown()` 做了 HTML escape + 标签/属性清理，但 `userListContainerEl.innerHTML = userRows + orphanRows`（第 2893 行）直接拼接 HTML 字符串，如果用户名包含恶意内容可能存在 XSS 风险。

---

## 四、安全相关

### 11. CSP 中有 unsafe-inline

`style-src` 允许 `'unsafe-inline'`，降低了 CSP 对 XSS 的防护效果。

### 12. 无 CORS 配置

后端没有设置 `Access-Control-Allow-Origin` 头。目前前后端同源所以没问题，但如果将来分离部署需要补充。

---

## 五、其他

### 13. config/providers.json 几乎为空

文件只有 22 字节（`{}`），但 `.env.local.example` 中的 API key 变量名暗示有多个 provider 配置。文档和实际状态不一致。

### 14. tmp/ 目录大文件

约 300MB 的 jsonl 聊天记录和 PNG 图片。已被 `.gitignore` 排除，git 未跟踪，仅为磁盘占用问题。

### 15. 根目录 __pycache__/ 残留

存在 `/root/Threadloom/__pycache__/` 目录，说明曾在项目根目录直接运行过测试。已被 `.gitignore` 排除，属于环境不整洁。

---

## 总结

| 类别 | 严重程度 | 数量 |
|------|----------|------|
| 类型错误 | 中 | 10 |
| 测试失败/坏测试 | 中 | 6 |
| 异常吞没 | 中 | 114 处 |
| 非原子写入 | 中 | ~10 处 |
| 并发竞态风险 | 中 | 多处 |
| XSS 风险点 | 低-中 | 1-2 处 |
| 工程规范缺失 | 低 | 依赖管理 |

项目核心安全做得不错（bcrypt 密码哈希、路径遍历检查、登录限速、CSP headers、SSRF 防护），主要问题集中在代码质量和工程规范层面。

---

## 复核与处理状态（Sisyphus，2026-05-10）

### 已修复

- **依赖管理文件**：已新增 `requirements.txt`，包含当前实际 Python 运行/测试依赖。`jieba` 未发现代码引用，未加入依赖。
- **测试失败 / 坏测试**：已修正会被 pytest 误收集的脚本型 helper 命名；`test_llama_quality` 已避免 0 成功请求时除零；`test_full_regression` 已更新 stale API 调用；`test_card_importer` 已修正类型诊断。
- **pyright 类型错误**：已清理本次审计列出的 backend/tests error 级诊断。
- **非原子写入**：已补充/复用原子写入路径，覆盖 runtime_store、model_config、player_profile、character_manager、card_importer、lorebook_distiller、user_manager、SillyTavern import、rebuild report 等关键可变写入点。
- **文件写入竞态**：已为 model config 与 player profile/avatar 写入增加模块级锁，并保留已有 session/user/system 锁。
- **localStorage token**：前端不再把 session token 持久化到 `localStorage`；token 仅保留在页面内存中，后端 `/api/auth/me` 可通过 HttpOnly cookie 为当前页面恢复内存 token。

### 延后处理 / 接受风险

- **异常吞没**：确认存在，但很多是 LLM/解析 fallback；不适合一次性机械修改。后续应按持久化、认证、配置、导入链路逐步收敛。
- **单文件过大**：确认是维护性问题，不作为本轮 bugfix 范围。
- **CSP `unsafe-inline`**：确认存在，但当前前端仍有 JS 动态 style 写入；本轮未移除，避免破坏 UI。后续若要修，应先把动态样式切到 class/CSS variable，再收紧 CSP。

### 误报 / 当前不需要修复

- **事件监听器无清理**：当前主要是静态 SPA 初始化与容器事件委托，没有发现实际动态 mount/unmount 泄漏点。
- **user list `innerHTML` XSS**：审计指出的 username/orphan-dir 路径已通过 `escapeHtml()` 处理；可后续改 DOM 构造硬化，但不是当前漏洞。
- **无 CORS 配置**：同源部署下不需要 CORS；不要添加宽松 CORS。仅当前后端拆分部署时再加 allowlist。
- **`config/providers.json` 为空**：这是被 gitignore 的本地配置；已有 `config/providers.example.json`。属于文档/示例说明问题，不是代码 bug。
- **`tmp/` 大文件、根目录 `__pycache__`**：环境清理项，不是代码修复项。
- **`jieba` 依赖**：当前代码无 `import jieba` / `from jieba import ...`，视为历史残留/审计误提，不需要加入依赖。
