# Security Audit 2026-04-29

## Scope

本次审计覆盖当前本地单用户产品面的后端 HTTP 入口、模型站点配置、上传/导入接口、前端消息渲染、CSP 与运行时 trace 默认值。

## Fixed findings

- 后端默认监听从 `0.0.0.0` 收紧为 `127.0.0.1`，避免原型服务在无认证状态下暴露到局域网或公网。
- 所有 JSON `POST` / `DELETE` 请求在读取 body 前检查 `Content-Length`，默认上限为 `16 MiB`，降低大请求体和 base64 上传导致的内存耗尽风险。
- HTTP 响应统一增加基础安全头：`X-Content-Type-Options: nosniff`、`Referrer-Policy`、`X-Frame-Options: DENY`、`Permissions-Policy`；JSON API 响应增加 `Cache-Control: no-store`。
- HTML CSP 增加 `object-src 'none'`、`base-uri 'self'`、`frame-ancestors 'none'`，服务端响应头与页面 meta 保持一致。
- provider `baseUrl` 增加服务端校验：远程站点必须使用 HTTPS；私网、link-local、multicast、reserved、unspecified IP 被拒绝；`localhost` / `127.0.0.1` / `::1` 保留给本机模型服务。
- provider `baseUrl` 变更且未重新输入 API key 时，旧 key 会被清空，避免旧密钥被转发到新端点。
- 前端 assistant markdown 渲染增加轻量净化：移除危险标签、事件处理属性、`style` 属性，以及非本地/HTTP(S)/锚点链接，降低 stored HTML injection 风险。
- `config/runtime*.json` 默认关闭 turn trace，避免默认落盘 prompt、history、profile 等敏感上下文。

## Verification

- `python3 -m py_compile backend/server.py backend/model_config.py`
- `python3 -m pytest tests/test_model_client.py tests/test_context_builder.py tests/test_state_fragment.py`
- 手动验证：SSRF URL 拦截、localhost 例外、安全响应头、监听地址、切换 provider URL 清空旧 API key。

## Remaining risks

- 当前产品面仍是单用户本地原型，未提供正式多用户鉴权。若需要暴露到其他机器，应放在可信反向代理后，并补全认证、CSRF、TLS 与访问控制策略。
- 前端 markdown 净化为内置轻量实现；若未来允许更复杂 HTML/markdown，建议改为受维护的 sanitizer（如 DOMPurify）并固定依赖来源。
- provider URL 目前只做语法与直接 IP 分类校验，未做 DNS 解析后的最终 IP 校验；若站点配置未来对不可信用户开放，需要增加 DNS rebinding 防护或 provider allowlist。
- `stitch*.html` 仍是原型静态页面，包含第三方 CDN 脚本；正式入口仍是 `frontend/index.html`。
