# Threadloom — Pre-deployment Security Audit

Audit date: 2026-05-05
Scope: full repository at `/root/Threadloom` (HEAD of `master`).

## Executive summary

**结论 / Verdict: 整体安全水平良好，建议修复 1 个中危 + 落实部署清单后再上公网。Overall posture is solid; address the one Medium below and complete the hardening checklist before exposing on the public internet.**

The backend (`backend/server.py`) is a hand-written `BaseHTTPRequestHandler` app with no SQL, no template engine, and no shell/eval. Auth, CSRF, SSRF, path-traversal, login throttling, file permissions, and bind-host gating are already implemented thoughtfully. No deploy-blocking issues found. No indicators of prior compromise.

## Critical (deploy blockers)

Checked, none found.

## High

Checked, none found.

## Medium

### M1 — `/api/auth/me` reflects unvalidated bearer token into `Set-Cookie`
File: `backend/server.py:564-573`

```
token = self._extract_token()
headers = {'Set-Cookie': auth_cookie_header(token)} if uid and token else None
```

`uid` comes from `resolve_user_from_request` (which does validate the token), but the Set-Cookie value is built directly from the raw `Authorization: Bearer …` header without re-validating the *exact* string we are about to write into a cookie. `auth_cookie_header` interpolates with an f-string and does not sanitize CR/LF or `;`. A malicious client supplying e.g. `Authorization: Bearer goodtoken\r\nSet-Cookie: x=y` would, in theory, smuggle headers via the BaseHTTPServer write path. `BaseHTTPRequestHandler.send_header` does forbid `\n`, so this is mitigated in practice — but the value is still attacker-controlled and ends up in a cookie that survives 30 days.

Fix: either drop the `Set-Cookie` reflection on `/api/auth/me` (the cookie is already issued at `/api/auth/login`), or validate that `token` matches `[A-Za-z0-9_\-]+` before reflecting.

## Low / hygiene

### L1 — Login throttle keyed on `client_address[0]` is fooled by reverse proxies
File: `backend/server.py:991`, `186-199`

`check_login_throttle` uses the raw TCP peer IP. Once you front the service with Nginx/Caddy, every login looks like it comes from `127.0.0.1` and the per-IP cap (12/min) becomes a global cap. Either keep loopback rejection in the proxy and/or read `X-Forwarded-For` *only* when the peer is the trusted proxy. Don't blindly trust the header.

### L2 — Avatar / cover responses have no `Content-Length` cap on the read side
File: `backend/server.py:511-524`, `689-707`

Avatar uploads are capped at 5 MB on POST, but the GET path `read_bytes()` happily streams arbitrary local files. Today the path is constrained to user-owned dirs, so this is informational; if someone ever adds a symlink under `runtime-data/`, you'd serve whatever it points to. Consider rejecting symlinks during avatar/cover save.

### L3 — `parse_json_response` has fragile JSON-repair heuristics
File: `backend/local_model_client.py:93-135`

Not a security issue, but the truncation-recovery code has been bitten by attackers in similar agents. Make sure no path passes user-controllable text through `parse_json_response` for trust-bearing decisions.

### L4 — `tmp/` contains imported character cards with active-content potential
Files include `tmp/TGbreak😺V*.json`, `tmp/双人成行 V5.0 ...json`, etc.

These are SillyTavern card payloads — *system prompts* the LLM will execute as instructions if loaded. Treat every card as untrusted input. The current code never `eval`s card content, but the LLM agent surface (`backend/handler_message.py` etc.) **is** the prompt-injection sink. There are no LLM-callable tools that touch FS/network/shell in `backend/tools/` (only `rebuild_session_from_history.py` and `replay_turn_trace.py`, both CLI-only) — so today the blast radius of a malicious card is limited to the LLM's text output. Keep it that way: do not grant the narrator any new tools that take string args and call shell/HTTP without re-validating.

### L5 — `local_model_client.py:65` uses `urllib.request.urlopen` directly
File: `backend/local_model_client.py:65`

This bypasses `safe_http`. It's only invoked for *local* model inference where the URL is operator-set, so practical SSRF risk is low — but if you ever expose `local model base_url` editing to non-admin users, this becomes SSRF. Route this call through `safe_http.open_safe_connection` for consistency.

### L6 — Public path list includes the full frontend bundle
File: `backend/server.py:79-93`

`/`, `/index.html`, `/app.js`, `/styles.css`, `/marked.min.js`, `/favicon.svg`, `/api/health`, `/api/auth/me`, `/api/auth/login`, `/api/auth/logout`, `/api/multi-user` are reachable without auth. That is correct (you need to serve the login page), but `/api/multi-user` being public is unusual — verify it really must be (it does enforce admin auth internally; the "public" allowance is just so the gate runs at all).

## Possible compromise indicators

Checked. None found.

- Single committer (`Codex <codex@local>`); all 30+ recent commits are coherent security-tightening work.
- No secrets in tracked files (`git log --all -p -S 'sk-'` returned only CSS `gap:` matches).
- `config/providers.json` exists locally but is empty (`{"providers": {}}`) and gitignored.
- `runtime-data/`, `sessions/`, `tmp/`, `.env.local`, `config/runtime.json`, `config/providers.json` all in `.gitignore`.
- No `.so`/`.pyd`/`.elf`/`.bin` artifacts outside `.venv-jieba/`.
- `runtime-data/` contains only normal session JSON written by the running app.
- `tmp/` contains user character cards and chat exports — large, but expected; nothing executable.

## Static-analysis checklist (what was checked)

| Category | Result |
| --- | --- |
| `eval` / `exec` / `os.system` / `subprocess` / `pickle` / `yaml.load` / `__import__` / `shell=True` | None present (only `ast.literal_eval` in `name_sanitizer.py:55` — safe) |
| SQL (any flavour), template engines (Jinja, etc.) | None — pure JSON file storage |
| Direct `urlopen` / `requests` / `httpx` / `aiohttp` | Only `local_model_client.py:65`; all external/user-supplied URLs go through `safe_http` (model_client, model_config) |
| SSRF defense | `safe_http.py` pre-resolves DNS, blocks RFC1918 / loopback / link-local / multicast / reserved, pins resolved IP onto the connection (defeats DNS rebinding) |
| Path traversal | `paths.py` defines `confine_to_root` / `confine_to_user_root`; session_id and turn_id are regex-validated; character_id is slugified; cover path is checked with `is_path_within_user_root` |
| File-upload limits | 16 MB request body, 5 MB avatar, 16 MB chat import; base64 validated; quota of 10 cards/user |
| Auth | bcrypt, constant-time path even for unknown users (dummy hash), 5-fail × 15 min lockout, login rate-limit per-IP and global, atomic 0o600 writes, token = `secrets.token_urlsafe(32)` stored only as SHA-256, 30 d TTL, max 10 active tokens/user |
| CSRF | POST/DELETE/PUT refuse cookie auth (`allow_cookie=False` at `server.py:123`), Bearer required; `business_payload_has_user_id` rejects business APIs that try to override `user_id` |
| Security headers | `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`, strict CSP for HTML; `Cache-Control: no-store` on JSON |
| Bind-host gate | `server.py:234-241` refuses non-loopback bind unless multi-user + admin password are set, with explicit override env var |
| Secrets in tracked files / git history | None |

## Deployment hardening checklist (do these before going public)

1. **Fix M1.** Either drop the cookie reflection at `server.py:565` or sanitize the token before reflecting.
2. **Set the admin password and enable multi-user *from the loopback host first*.** `set_admin_password` bootstrap is already loopback-gated (`server.py:1042`). Sequence:
   - Start backend on `127.0.0.1:8765` once.
   - From the same host, POST `/api/users action=set_admin_password` with a strong password.
   - POST `/api/multi-user enabled=true password=<that pwd>`.
3. **Run behind TLS-terminating reverse proxy.** Backend speaks plain HTTP. Use Nginx/Caddy with HTTPS, HSTS, and HTTP→HTTPS redirect. Bind backend on `127.0.0.1:8765` and proxy_pass from the public listener; do **not** set `THREADLOOM_HOST=0.0.0.0` directly.
4. **If you must bind on a public interface**, set both `THREADLOOM_HOST` and `THREADLOOM_ALLOW_PUBLIC_SINGLE_USER` only after step 2, and only behind external access control (firewall / VPN / mTLS).
5. **Firewall:** allow only 80/443 inbound to the proxy. Block port 8765 from the public side.
6. **Filesystem permissions:**
   ```
   chmod 700 /root/Threadloom/runtime-data
   chmod 700 /root/Threadloom/runtime-data/_system
   chmod 600 /root/Threadloom/runtime-data/_system/users.json
   chmod 600 /root/Threadloom/runtime-data/_system/sessions.json
   chmod 600 /root/Threadloom/config/providers.json /root/Threadloom/config/runtime.json
   chmod 600 /root/Threadloom/.env.local   # if/when you create it
   ```
   The server already self-tightens `users.json` / `sessions.json` to 0o600 on startup; the rest is up to you.
7. **Run as a non-root user.** Currently running as root (per `ls -la`). Create a dedicated `threadloom` user, `chown -R` the project, and run the daemon as that user. Containerisation is fine too.
8. **Logs:** `backend/threadloom.log` is world-readable today. `chmod 640` and rotate (`logrotate`) — these logs include client IPs and request paths.
9. **Configure proxy rate-limit.** Backend's per-IP login throttle assumes the peer IP is the real client; once behind a proxy, enforce rate limiting at the proxy layer too (Nginx `limit_req_zone`).
10. **Prune `tmp/`** before deploying. Files there are private SillyTavern cards / chat exports unrelated to runtime; they don't need to ship to the production host.
11. **Set conservative CORS** at the proxy if you ever serve the frontend from a different origin. The backend has no CORS handling — same-origin is assumed.
12. **Rotate any API keys** referenced by `.env.local` / `config/providers.json` if those files have ever existed on a shared machine; nothing was committed to git, but local copies are cheap to rotate.
13. **Disable directory listing** at the proxy.
14. **Backup / disaster recovery:** snapshot `runtime-data/` regularly; users.json + per-user character dirs are the only durable state.
