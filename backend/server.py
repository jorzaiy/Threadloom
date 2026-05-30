#!/usr/bin/env python3
import errno
import ipaddress
import json
import logging
import os
import threading
import time
import sys
import weakref
from base64 import b64decode
from contextlib import contextmanager
from contextvars import Token
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from character_manager import delete_character_card, import_character_card_base64, list_character_cards, rebuild_character_lorebook, set_active_character
from handler_message import handle_message
from import_sillytavern_chat import import_sillytavern_from_content, preview_chat_import
from model_config import (
    delete_narrator_preset,
    delete_provider_config,
    discover_provider_models,
    discover_site_models,
    get_model_config_snapshot,
    get_site_config_snapshot,
    load_narrator_preset,
    list_provider_configs,
    save_narrator_preset,
    SiteConfigPermissionError,
    update_model_config,
    update_site_config,
    upsert_provider_config,
)
from regenerate_turn import delete_latest_turn, regenerate_last_partial
from session_auditor import run_session_audit
from session_lifecycle import delete_session, list_sessions, start_new_game
from paths import DEFAULT_USER_ID, active_character_id, active_user_id, current_session_dir, find_character_session_dir, is_path_within_user_root, normalize_session_id, resolve_session_dir, reset_active_user_id, reset_multi_user_request_context, set_active_user_id, set_multi_user_request_context, slugify
from player_profile import base_player_profile_source_path, character_player_profile_override_source_path, delete_user_avatar, legacy_profile_to_unified, load_base_player_profile, load_character_player_profile_override, normalize_profile_text_with_keeper_llm, read_profile_source, render_runtime_player_profile_markdown, resolve_user_avatar_path, save_base_player_profile, save_base_player_profile_source, save_character_player_profile_override, save_character_player_profile_override_source, save_user_avatar, validate_unified_player_profile
from runtime_store import build_entity_map, build_state_snapshot, filter_committed_history_items, load_character_card_meta, load_history, load_state, resolve_character_cover_path, web_runtime_settings
from user_manager import (
    admin_has_password, archive_orphan_user_dir, change_own_password, create_user, delete_user, disable_user, enable_user,
    list_user_storage_audit, list_users, login, logout,
    is_multi_user_enabled, set_multi_user_enabled,
    reset_user_password, set_admin_password, resolve_user_from_request, validate_token,
)


HOST = os.environ.get('THREADLOOM_HOST', '127.0.0.1') or '127.0.0.1'
try:
    PORT = int(os.environ.get('THREADLOOM_PORT', '8765') or 8765)
except ValueError:
    PORT = 8765
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_CHAT_IMPORT_BYTES = 16 * 1024 * 1024
# WeakValueDictionary so a session_id's lock disappears once no caller holds
# it, instead of accumulating one entry per session_id ever seen for the
# lifetime of the process. Concurrent callers naturally pin the same lock
# alive while the ``with`` block is active.
SESSION_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
SESSION_LOCKS_GUARD = threading.Lock()
LOGIN_THROTTLE_LOCK = threading.Lock()
LOGIN_ATTEMPTS_BY_IP: dict[str, list[float]] = {}
LOGIN_ATTEMPTS_GLOBAL: list[float] = []
LOGIN_IP_WINDOW_SECONDS = 60
LOGIN_IP_LIMIT = 12
LOGIN_GLOBAL_WINDOW_SECONDS = 60
LOGIN_GLOBAL_LIMIT = 80


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('threadloom.server')
MULTI_USER_PRODUCT_ENABLED = True

PUBLIC_GET_PATHS = {
    '/',
    '/index.html',
    '/login.js',
    '/marked.min.js',
    '/styles.css',
    '/favicon.svg',
    '/api/health',
    '/api/auth/me',
}
PUBLIC_POST_PATHS = {
    '/api/auth/login',
    '/api/auth/logout',
    '/api/multi-user',
}
USER_ASSET_CACHE_HEADERS = {'Cache-Control': 'no-store'}


_SAFE_TOKEN_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')


def is_safe_session_token(token: str) -> bool:
    # secrets.token_urlsafe(32) only emits URL-safe base64 characters; rejecting
    # anything outside that alphabet stops attacker-controlled bytes (CR, LF, ;)
    # from being interpolated into Set-Cookie when /api/auth/me reflects the
    # caller's bearer token back as a cookie.
    return bool(token) and len(token) <= 256 and all(ch in _SAFE_TOKEN_CHARS for ch in token)


def auth_cookie_header(token: str) -> str:
    return f'session_token={token}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax'


def clear_auth_cookie_header() -> str:
    return 'session_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax'


def is_valid_character_id_param(character_id: str) -> bool:
    value = str(character_id or '').strip()
    return bool(value) and slugify(value, 'character') == value


def _public_paths_for_method(method: str) -> set[str]:
    if method == 'GET':
        return PUBLIC_GET_PATHS
    if method == 'POST':
        return PUBLIC_POST_PATHS
    return set()


def begin_request_user_context(path: str, method: str, headers: dict[str, str]) -> tuple[str | None, Token[str] | None, bool]:
    public_paths = _public_paths_for_method(method)
    # State-changing requests refuse Cookie auth so a browser-issued cross-site
    # POST cannot ride a session_token cookie. Bearer header is required for
    # POST/DELETE/PUT regardless of how the frontend stores the token.
    allow_cookie = method == 'GET'
    uid = resolve_user_from_request(headers, allow_cookie=allow_cookie)
    if is_multi_user_enabled() and uid is None and path not in public_paths:
        return None, None, False
    token = set_active_user_id(uid or DEFAULT_USER_ID)
    return uid or DEFAULT_USER_ID, token, True


def begin_multi_user_request_context() -> Token[bool]:
    return set_multi_user_request_context(is_multi_user_enabled())


def payload_string(payload: dict, key: str, *, required: bool = True) -> str:
    value = payload.get(key)
    if value is None:
        if required:
            raise ValueError(f'{key} is required')
        return ''
    if not isinstance(value, str):
        raise ValueError(f'{key} must be a string')
    text = value.strip() if key != 'password' else value
    if required and not text:
        raise ValueError(f'{key} is required')
    return text


def payload_bool(payload: dict, key: str, *, required: bool = True) -> bool:
    value = payload.get(key)
    if value is None:
        if required:
            raise ValueError(f'{key} is required')
        return False
    if not isinstance(value, bool):
        raise ValueError(f'{key} must be a boolean')
    return value


def decode_base64_limited(content_base64: str, *, max_bytes: int, label: str) -> bytes:
    try:
        data = b64decode(content_base64.encode('utf-8'), validate=True)
    except Exception as err:
        raise ValueError(f'invalid {label} payload') from err
    if len(data) > max_bytes:
        raise ValueError(f'{label} payload is too large')
    return data


def decode_chat_import_content(content_base64: str) -> str:
    return decode_base64_limited(content_base64, max_bytes=MAX_CHAT_IMPORT_BYTES, label='chat').decode('utf-8')


def authenticated_admin_from_token(token: str) -> str | None:
    if not token or not admin_has_password():
        return None
    uid = validate_token(token)
    return uid if uid == DEFAULT_USER_ID else None


def _prune_attempts(items: list[float], now: float, window: int) -> list[float]:
    cutoff = now - window
    return [item for item in items if item >= cutoff]


def check_login_throttle(client_ip: str) -> bool:
    now = time.time()
    key = client_ip or 'unknown'
    with LOGIN_THROTTLE_LOCK:
        global LOGIN_ATTEMPTS_GLOBAL
        LOGIN_ATTEMPTS_GLOBAL = _prune_attempts(LOGIN_ATTEMPTS_GLOBAL, now, LOGIN_GLOBAL_WINDOW_SECONDS)
        ip_attempts = _prune_attempts(LOGIN_ATTEMPTS_BY_IP.get(key, []), now, LOGIN_IP_WINDOW_SECONDS)
        if len(LOGIN_ATTEMPTS_GLOBAL) >= LOGIN_GLOBAL_LIMIT or len(ip_attempts) >= LOGIN_IP_LIMIT:
            LOGIN_ATTEMPTS_BY_IP[key] = ip_attempts
            return False
        ip_attempts.append(now)
        LOGIN_ATTEMPTS_BY_IP[key] = ip_attempts
        LOGIN_ATTEMPTS_GLOBAL.append(now)
        return True


def is_loopback_host(host: str) -> bool:
    text = str(host or '').strip().lower()
    if text == 'localhost':
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def is_loopback_client(client_ip: str) -> bool:
    return is_loopback_host(client_ip)


def startup_security_check() -> None:
    from user_manager import SESSIONS_FILE, USERS_FILE, _save_sessions, _load_sessions
    for path in (USERS_FILE, SESSIONS_FILE):
        if path.exists():
            mode = path.stat().st_mode & 0o777
            if mode != 0o600:
                try:
                    os.chmod(path, 0o600)
                    logger.warning('tightened permissions on %s from %o to 600', path, mode)
                except OSError as err:
                    logger.warning('could not tighten permissions on %s: %s', path, err)
    if SESSIONS_FILE.exists():
        _save_sessions(_load_sessions())
    multi_user_enabled = is_multi_user_enabled()
    has_admin_password = admin_has_password()
    if multi_user_enabled and not has_admin_password:
        logger.error('multi-user mode is enabled but default-user has no admin password; reset users.json or set an admin password before starting')
        raise SystemExit(1)
    if not is_loopback_host(HOST) and (not multi_user_enabled or not has_admin_password):
        if os.environ.get('THREADLOOM_ALLOW_PUBLIC_SINGLE_USER') == '1':
            logger.warning('UNSAFE OVERRIDE: starting on non-loopback host %s without multi-user auth fully enabled', HOST)
        else:
            logger.error('refusing to bind %s without multi-user enabled and an admin password; set both locally first or use THREADLOOM_ALLOW_PUBLIC_SINGLE_USER=1 only behind external access control', HOST)
            raise SystemExit(1)
    if multi_user_enabled and not is_loopback_host(HOST):
        logger.warning('multi-user mode is enabled while listening on non-loopback host %s; use TLS and a trusted reverse proxy', HOST)


def is_admin_password_bootstrap_action(action: str) -> bool:
    return action == 'set_admin_password' and not is_multi_user_enabled() and not admin_has_password()


def allows_user_id_payload(path: str) -> bool:
    return path in {'/api/auth/login', '/api/users'}


def business_payload_has_user_id(path: str, payload: dict) -> bool:
    return not allows_user_id_payload(path) and 'user_id' in payload


def business_query_has_user_id(path: str, query: dict[str, list[str]]) -> bool:
    return not allows_user_id_payload(path) and 'user_id' in query


def _experimental_disabled_payload(feature: str) -> dict:
    return {
        'error': {
            'code': 'EXPERIMENTAL_DISABLED',
            'message': f'{feature} is disabled in the current single-user product mode',
        }
    }


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    server_version = 'Threadloom/0.1'

    def _session_exists(self, session_id: str) -> bool:
        session_dir = resolve_session_dir(session_id, create=False)
        return session_dir.exists() and (session_dir / 'context.json').exists()

    def _validate_active_session_scope(self, session_id: str, *, allow_missing: bool = False) -> bool:
        current = current_session_dir(session_id)
        if current.exists():
            return True
        other = find_character_session_dir(session_id, exclude_active=True)
        if other is not None:
            self._send(409, {
                'error': {
                    'code': 'SESSION_CHARACTER_MISMATCH',
                    'message': 'session belongs to a different character; switch back to that character before using it',
                }
            })
            return False
        if allow_missing:
            return True
        self._send(404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'session not found'}})
        return False

    def _invalid_input(self, message: str):
        return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': message}})

    def _is_client_disconnect(self, err: Exception) -> bool:
        if isinstance(err, (BrokenPipeError, ConnectionResetError)):
            return True
        if isinstance(err, OSError) and err.errno in {errno.EPIPE, errno.ECONNRESET}:
            return True
        return False

    def _send_raw(self, status: int, body: bytes, *, content_type: str, extra_headers: dict[str, str] | None = None):
        try:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            headers = self._security_headers(content_type)
            headers.update(extra_headers or {})
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
            return True
        except Exception as err:
            if self._is_client_disconnect(err):
                logger.info('Client disconnected before response could be sent on %s', self.path)
                return False
            raise

    def _security_headers(self, content_type: str) -> dict[str, str]:
        headers = {
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'X-Frame-Options': 'DENY',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        }
        if content_type.startswith('text/html'):
            headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if content_type.startswith('application/json'):
            headers['Cache-Control'] = 'no-store'
        return headers

    def _read_json_payload(self) -> dict | None:
        try:
            length = int(self.headers.get('Content-Length', '0') or 0)
        except ValueError:
            self._invalid_input('invalid content length')
            return None
        if length > MAX_REQUEST_BYTES:
            self._send(413, {'error': {'code': 'PAYLOAD_TOO_LARGE', 'message': 'request body is too large'}})
            return None
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            data = json.loads(raw.decode('utf-8'))
        except Exception:
            self._invalid_input('invalid json')
            return None
        if not isinstance(data, dict):
            self._invalid_input('json payload must be an object')
            return None
        return data

    def _payload_string(self, payload: dict, key: str, *, required: bool = True) -> str | None:
        try:
            return payload_string(payload, key, required=required)
        except ValueError as err:
            self._invalid_input(str(err))
            return None

    def _send(self, status: int, payload: dict, *, extra_headers: dict[str, str] | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return self._send_raw(
            status,
            body,
            content_type='application/json; charset=utf-8',
            extra_headers=extra_headers,
        )

    def _send_login_page(self):
        body = '''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Threadloom 登录</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;700&family=Inter:wght@400;500;700&family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="stylesheet" href="/styles.css" />
    <script src="/login.js" defer></script>
  </head>
  <body>
    <div id="loginScreen" class="login-screen">
      <form id="loginForm" class="login-form" autocomplete="on">
        <h1 class="login-title"><img src="/favicon.svg" alt="" class="brand-logo" />Threadloom 登录</h1>
        <p class="login-hint">多用户模式已启用，请输入账号信息。</p>
        <label class="login-field">
          <span>用户名</span>
          <input id="loginUserId" type="text" autocomplete="username" required />
        </label>
        <label class="login-field">
          <span>密码</span>
          <input id="loginPassword" type="password" autocomplete="current-password" required />
        </label>
        <div id="loginError" class="login-error" role="alert"></div>
        <button id="loginSubmitBtn" type="submit" class="primary">登录</button>
      </form>
    </div>
  </body>
</html>
'''.encode('utf-8')
        return self._send_raw(200, body, content_type='text/html; charset=utf-8')

    def log_message(self, format: str, *args):
        logger.info('%s - %s', self.address_string(), format % args)

    def _handle_exception(self, err: Exception, *, route: str):
        if self._is_client_disconnect(err):
            logger.info('Client disconnected during %s: %s', route, err)
            return None
        logger.exception('Unhandled request error on %s: %s', route, err)
        try:
            return self._send(500, {'error': {'code': 'INTERNAL_ERROR', 'message': 'internal server error'}})
        except Exception as send_err:
            if self._is_client_disconnect(send_err):
                logger.info('Client disconnected before error response could be sent on %s', route)
                return None
            raise

    def _session_lock(self, session_id: str) -> threading.Lock:
        with SESSION_LOCKS_GUARD:
            lock_key = str(resolve_session_dir(session_id, create=False).resolve(strict=False))
            lock = SESSION_LOCKS.get(lock_key)
            if lock is None:
                lock = threading.Lock()
                SESSION_LOCKS[lock_key] = lock
            return lock

    def _extract_token(self) -> str:
        # Bearer-only: admin auth paths must not honour browser-issued cookies
        # because admin actions are state-changing and CSRF-relevant. Cookie
        # auth remains available for ordinary GET requests via
        # ``begin_request_user_context``'s allow_cookie branch.
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        return ''

    def _extract_cookie_token(self) -> str:
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            item = part.strip()
            if item.startswith('session_token='):
                return item[len('session_token='):]
        return ''

    def _authenticated_admin_user(self) -> str | None:
        return authenticated_admin_from_token(self._extract_token())

    def _begin_request_user(self, path: str, method: str) -> tuple[str | None, Token[str] | None, bool]:
        uid, token, ok = begin_request_user_context(path, method, dict(self.headers))
        if not ok:
            self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': 'login required'}})
            return None, None, False
        return uid, token, True

    @contextmanager
    def _request_scope(self, method: str):
        # Shared request envelope for every verb: resolve the per-request user
        # context, mirror it into the multi-user contextvar, and ALWAYS reset
        # both on the way out (any return or raise inside the ``with`` block).
        # This replaces the token-reset blocks that were previously duplicated
        # at every early return in do_GET / do_POST / do_DELETE.
        parsed = urlparse(self.path)
        _, user_token, authorized = self._begin_request_user(parsed.path, method)
        multi_user_token = begin_multi_user_request_context() if authorized else None
        try:
            yield parsed, authorized
        finally:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)

    def _resolve_scoped_session(self, raw: str, *, allow_missing: bool) -> str | None:
        # Normalize a session_id and confirm it belongs to the active character.
        # On any failure the matching 400/404/409 response is sent and None is
        # returned, so callers simply ``return`` on None.
        session_id = str(raw or '').strip()
        if not session_id:
            self._invalid_input('session_id is required')
            return None
        try:
            session_id = normalize_session_id(session_id)
        except ValueError as err:
            self._invalid_input(str(err))
            return None
        if not self._validate_active_session_scope(session_id, allow_missing=allow_missing):
            return None
        return session_id

    def do_GET(self):
        with self._request_scope('GET') as (parsed, authorized):
            if not authorized:
                return
            qs = parse_qs(parsed.query, keep_blank_values=True)
            if business_query_has_user_id(parsed.path, qs):
                return self._invalid_input('business API must not include user_id')
            try:
                handler = self._GET_ROUTES.get(parsed.path)
                if handler is None:
                    return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
                return handler(self, parsed, qs)
            except Exception as err:
                return self._handle_exception(err, route=parsed.path)

    def _get_health(self, parsed, qs):
        return self._send(200, {
            'ok': True,
            'service': 'threadloom-backend',
            'host': HOST,
            'port': PORT,
        })

    def _get_state(self, parsed, qs):
        session_id = self._resolve_scoped_session((qs.get('session_id') or [''])[0], allow_missing=True)
        if session_id is None:
            return
        if not self._session_exists(session_id):
            return self._send(200, {
                'session_id': session_id,
                'state': build_state_snapshot({}),
                'character_card': load_character_card_meta(),
                'web': web_runtime_settings(),
            })
        state = load_state(session_id)
        return self._send(200, {
            'session_id': session_id,
            'state': build_state_snapshot(state),
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _get_sessions(self, parsed, qs):
        sessions = list_sessions()
        default_session_id = next((item['session_id'] for item in sessions if not item.get('archived') and not item.get('replay')), '')
        return self._send(200, {
            'sessions': sessions,
            'default_session_id': default_session_id,
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _get_providers(self, parsed, qs):
        payload = list_provider_configs()
        payload['web'] = web_runtime_settings()
        return self._send(200, payload)

    def _get_characters(self, parsed, qs):
        return self._send(200, {
            'characters': list_character_cards(),
            'active_character_id': load_character_card_meta().get('character_id', ''),
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _get_user_profile(self, parsed, qs):
        profile = load_base_player_profile()
        try:
            profile = validate_unified_player_profile(profile)
        except ValueError:
            profile = legacy_profile_to_unified(profile)
        return self._send(200, {
            'profile': profile,
            'source_text': read_profile_source(base_player_profile_source_path()),
            'prompt_preview': render_runtime_player_profile_markdown(profile),
            'avatar_url': '/user-avatar' if resolve_user_avatar_path() else None,
            'web': web_runtime_settings(),
        })

    def _get_character_profile_override(self, parsed, qs):
        override = load_character_player_profile_override()
        try:
            override = validate_unified_player_profile(override)
        except ValueError:
            override = legacy_profile_to_unified(override)
        return self._send(200, {
            'override': override,
            'source_text': read_profile_source(character_player_profile_override_source_path()),
            'prompt_preview': render_runtime_player_profile_markdown(override),
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _get_user_avatar(self, parsed, qs):
        avatar_path = resolve_user_avatar_path()
        if not avatar_path or not avatar_path.exists():
            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'avatar not found'}})
        content_type = 'image/png'
        if avatar_path.suffix.lower() in {'.jpg', '.jpeg'}:
            content_type = 'image/jpeg'
        elif avatar_path.suffix.lower() == '.webp':
            content_type = 'image/webp'
        return self._send_raw(
            200,
            avatar_path.read_bytes(),
            content_type=content_type,
            extra_headers=USER_ASSET_CACHE_HEADERS,
        )

    def _get_site_config(self, parsed, qs):
        payload = get_site_config_snapshot()
        if active_user_id() != DEFAULT_USER_ID:
            payload.pop('api_key_masked', None)
            payload.pop('api_key_reference', None)
        payload['supported_api_types'] = list_provider_configs()['supported_api_types']
        payload['web'] = web_runtime_settings()
        return self._send(200, payload)

    def _get_model_config(self, parsed, qs):
        payload = get_model_config_snapshot()
        payload['web'] = web_runtime_settings()
        return self._send(200, payload)

    def _get_narrator_preset(self, parsed, qs):
        preset_id = (qs.get('preset_id') or qs.get('id') or [''])[0].strip()
        try:
            return self._send(200, load_narrator_preset(preset_id))
        except ValueError as err:
            return self._invalid_input(str(err))

    def _get_users(self, parsed, qs):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('multi-user management'))
        caller = self._authenticated_admin_user()
        if caller != DEFAULT_USER_ID:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可查看用户列表'}})
        return self._send(200, {
            'users': list_users(),
            'storage': list_user_storage_audit(),
            'multi_user_enabled': is_multi_user_enabled(),
        })

    def _get_auth_me(self, parsed, qs):
        uid = resolve_user_from_request(dict(self.headers))
        if is_multi_user_enabled() and uid is None:
            return self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': 'login required'}})
        role = 'admin' if uid == DEFAULT_USER_ID else 'user'
        token = self._extract_token() or self._extract_cookie_token()
        headers = {'Set-Cookie': auth_cookie_header(token)} if uid and is_safe_session_token(token) else None
        # admin_has_password lets the frontend know whether the
        # "enable multi-user" wizard needs to set a password first.
        payload = {
            'user_id': uid or '',
            'role': role,
            'multi_user_enabled': is_multi_user_enabled(),
            'admin_has_password': admin_has_password(),
            'token': token if uid and is_safe_session_token(token) else '',
        }
        if headers:
            return self._send(200, payload, extra_headers=headers)
        return self._send(200, payload)

    def _get_history(self, parsed, qs):
        session_id = self._resolve_scoped_session((qs.get('session_id') or [''])[0], allow_missing=True)
        if session_id is None:
            return
        before_raw = (qs.get('before') or [''])[0].strip()
        before: int | None = None
        if before_raw:
            try:
                before = int(before_raw)
            except ValueError:
                return self._invalid_input('before must be an integer')
            if before < 0:
                return self._invalid_input('before must be >= 0')
        if not self._session_exists(session_id):
            return self._send(200, {
                'session_id': session_id,
                'messages': [],
                'has_more': False,
                'next_before': None,
                'total_count': 0,
                'character_card': load_character_card_meta(),
                'web': web_runtime_settings(),
            })
        page_size = web_runtime_settings().get('history_page_size', 80)
        all_messages = filter_committed_history_items(load_history(session_id))
        total_count = len(all_messages)
        end = total_count if before is None else min(before, total_count)
        start = max(0, end - page_size)
        messages = all_messages[start:end]
        return self._send(200, {
            'session_id': session_id,
            'messages': messages,
            'has_more': start > 0,
            'next_before': start if start > 0 else None,
            'total_count': total_count,
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _get_entity(self, parsed, qs):
        entity_id = (qs.get('entity_id') or [''])[0].strip()
        session_id_raw = (qs.get('session_id') or [''])[0].strip()
        if not session_id_raw or not entity_id:
            return self._invalid_input('session_id and entity_id are required')
        session_id = self._resolve_scoped_session(session_id_raw, allow_missing=False)
        if session_id is None:
            return
        if not self._session_exists(session_id):
            return self._send(404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'session not found'}})
        state = load_state(session_id)
        entities = build_entity_map(state, session_id=session_id)
        entity = entities.get(entity_id)
        if not entity:
            return self._send(404, {'error': {'code': 'ENTITY_NOT_FOUND', 'message': 'entity not found'}})
        return self._send(200, {'session_id': session_id, 'entity': entity})

    def _get_index(self, parsed, qs):
        if is_multi_user_enabled() and not resolve_user_from_request(dict(self.headers), allow_cookie=True):
            return self._send_login_page()
        index_path = Path(__file__).resolve().parents[1] / 'frontend' / 'index.html'
        body = index_path.read_bytes()
        return self._send_raw(200, body, content_type='text/html; charset=utf-8')

    def _get_app_js(self, parsed, qs):
        app_path = Path(__file__).resolve().parents[1] / 'frontend' / 'app.js'
        body = app_path.read_bytes()
        return self._send_raw(200, body, content_type='application/javascript; charset=utf-8')

    def _get_login_js(self, parsed, qs):
        login_path = Path(__file__).resolve().parents[1] / 'frontend' / 'login.js'
        body = login_path.read_bytes()
        return self._send_raw(200, body, content_type='application/javascript; charset=utf-8')

    def _get_marked_js(self, parsed, qs):
        marked_path = Path(__file__).resolve().parents[1] / 'frontend' / 'marked.min.js'
        body = marked_path.read_bytes()
        return self._send_raw(200, body, content_type='application/javascript; charset=utf-8')

    def _get_styles_css(self, parsed, qs):
        css_path = Path(__file__).resolve().parents[1] / 'frontend' / 'styles.css'
        body = css_path.read_bytes()
        return self._send_raw(200, body, content_type='text/css; charset=utf-8')

    def _get_favicon(self, parsed, qs):
        icon_path = Path(__file__).resolve().parents[1] / 'frontend' / 'favicon.svg'
        if icon_path.exists():
            body = icon_path.read_bytes()
            return self._send_raw(200, body, content_type='image/svg+xml')
        # Missing favicon falls through to the same "unknown route" 404 the
        # original if-chain produced.
        return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})

    def _get_character_cover(self, parsed, qs):
        requested_character = (qs.get('character_id') or [''])[0].strip()
        requested_variant = (qs.get('variant') or [''])[0].strip()
        if requested_character and requested_character != active_character_id():
            if not is_valid_character_id_param(requested_character):
                return self._invalid_input('invalid character_id')
            from character_manager import current_user_character_root
            cover_path = None
            character_root = current_user_character_root() / requested_character
            asset_root = character_root / 'source' / 'assets'
            stems = [requested_variant] if requested_variant in {'cover-small', 'cover', 'cover-original'} else ['cover-small', 'cover', 'cover-original']
            for stem in stems:
                for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
                    candidate = asset_root / f'{stem}{ext}'
                    if candidate.exists():
                        cover_path = candidate
                        break
                if cover_path:
                    break
            if cover_path is None:
                imported_root = character_root / 'source' / 'imported'
                for candidate in sorted(imported_root.glob('*.original.*')):
                    if candidate.is_file():
                        cover_path = candidate
                        break
        else:
            cover_path = resolve_character_cover_path()
        if cover_path and cover_path.exists():
            if is_multi_user_enabled() and not is_path_within_user_root(cover_path):
                return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'cover not found'}})
            body = cover_path.read_bytes()
            mime = 'image/png'
            if cover_path.suffix.lower() in {'.jpg', '.jpeg'}:
                mime = 'image/jpeg'
            elif cover_path.suffix.lower() == '.webp':
                mime = 'image/webp'
            elif cover_path.suffix.lower() == '.gif':
                mime = 'image/gif'
            return self._send_raw(
                200,
                body,
                content_type=mime,
                extra_headers=USER_ASSET_CACHE_HEADERS,
            )
        # No matching cover falls through to the same "unknown route" 404.
        return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})

    _GET_ROUTES = {
        '/api/health': _get_health,
        '/api/state': _get_state,
        '/api/sessions': _get_sessions,
        '/api/providers': _get_providers,
        '/api/characters': _get_characters,
        '/api/user-profile': _get_user_profile,
        '/api/character/profile-override': _get_character_profile_override,
        '/user-avatar': _get_user_avatar,
        '/api/site-config': _get_site_config,
        '/api/model-config': _get_model_config,
        '/api/narrator-preset': _get_narrator_preset,
        '/api/users': _get_users,
        '/api/auth/me': _get_auth_me,
        '/api/history': _get_history,
        '/api/entity': _get_entity,
        '/': _get_index,
        '/index.html': _get_index,
        '/app.js': _get_app_js,
        '/login.js': _get_login_js,
        '/marked.min.js': _get_marked_js,
        '/styles.css': _get_styles_css,
        '/favicon.svg': _get_favicon,
        '/character-cover': _get_character_cover,
    }

    def do_POST(self):
        with self._request_scope('POST') as (parsed, authorized):
            if not authorized:
                return
            payload = self._read_json_payload()
            if payload is None:
                return
            if business_payload_has_user_id(parsed.path, payload):
                return self._invalid_input('business API must not include user_id')
            try:
                handler = self._POST_ROUTES.get(parsed.path)
                if handler is None:
                    return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
                return handler(self, parsed, payload)
            except Exception as err:
                return self._handle_exception(err, route=parsed.path)

    def _post_new_game(self, parsed, payload):
        session_id = self._resolve_scoped_session(payload.get('session_id', ''), allow_missing=True)
        if session_id is None:
            return
        with self._session_lock(session_id):
            return self._send(200, start_new_game(session_id))

    def _post_delete_session(self, parsed, payload):
        session_id = self._resolve_scoped_session(payload.get('session_id', ''), allow_missing=False)
        if session_id is None:
            return
        with self._session_lock(session_id):
            return self._send(200, delete_session(session_id))

    def _post_regenerate_last(self, parsed, payload):
        session_id = str(payload.get('session_id', '') or '').strip()
        if not session_id:
            return self._invalid_input('session_id is required')
        allow_complete = payload_bool(payload, 'allow_complete', required=False)
        scoped = self._resolve_scoped_session(session_id, allow_missing=False)
        if scoped is None:
            return
        session_id = scoped
        with self._session_lock(session_id):
            result = regenerate_last_partial(session_id, allow_complete=allow_complete)
        status = 200 if 'error' not in result else 400
        return self._send(status, result)

    def _post_delete_latest_turn(self, parsed, payload):
        session_id = self._resolve_scoped_session(payload.get('session_id', ''), allow_missing=False)
        if session_id is None:
            return
        with self._session_lock(session_id):
            result = delete_latest_turn(session_id)
            if 'error' not in result:
                result['messages'] = filter_committed_history_items(load_history(session_id))
                result['state_snapshot'] = build_state_snapshot(load_state(session_id))
                result['character_card'] = load_character_card_meta()
                result['web'] = web_runtime_settings()
        status = 200 if 'error' not in result else 400
        return self._send(status, result)

    def _post_message(self, parsed, payload):
        session_id = self._resolve_scoped_session(payload.get('session_id', ''), allow_missing=True)
        if session_id is None:
            return
        payload['session_id'] = session_id
        with self._session_lock(session_id):
            result = handle_message(payload)
        status = 200 if 'error' not in result else 400
        logger.info(
            'MESSAGE_STAGE stage=http_response_start session_id=%s turn_id=%s status=%s has_error=%s',
            session_id,
            result.get('turn_id', '-') if isinstance(result, dict) else '-',
            status,
            'error' in result if isinstance(result, dict) else True,
        )
        sent = self._send(status, result)
        logger.info(
            'MESSAGE_STAGE stage=http_response_sent session_id=%s turn_id=%s status=%s sent=%s',
            session_id,
            result.get('turn_id', '-') if isinstance(result, dict) else '-',
            status,
            bool(sent),
        )
        return sent

    def _post_session_audit(self, parsed, payload):
        session_id = self._resolve_scoped_session(payload.get('session_id', ''), allow_missing=False)
        if session_id is None:
            return
        if not self._session_exists(session_id):
            return self._send(404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'session not found'}})
        with self._session_lock(session_id):
            audit = run_session_audit(session_id)
        return self._send(200, {
            'session_id': session_id,
            'audit': audit,
            'web': web_runtime_settings(),
        })

    def _post_character_select(self, parsed, payload):
        try:
            result = set_active_character(str(payload.get('character_id', '') or ''))
        except ValueError as err:
            return self._invalid_input(str(err))
        result['character_card'] = load_character_card_meta()
        result['web'] = web_runtime_settings()
        return self._send(200, result)

    def _post_character_delete(self, parsed, payload):
        try:
            result = delete_character_card(str(payload.get('character_id', '') or ''))
        except ValueError as err:
            return self._invalid_input(str(err))
        result['character_card'] = load_character_card_meta()
        result['web'] = web_runtime_settings()
        return self._send(200, result)

    def _post_character_rebuild_lorebook(self, parsed, payload):
        try:
            result = rebuild_character_lorebook(str(payload.get('character_id', '') or ''))
        except ValueError as err:
            return self._invalid_input(str(err))
        result['character_card'] = load_character_card_meta()
        result['web'] = web_runtime_settings()
        return self._send(200, result)

    def _post_characters_import(self, parsed, payload):
        filename = str(payload.get('filename', '') or '').strip()
        file_base64 = str(payload.get('file_base64', '') or '').strip()
        target_name = str(payload.get('target_name', '') or '').strip()
        if not filename or not file_base64:
            return self._invalid_input('filename and file_base64 are required')
        try:
            result = import_character_card_base64(filename, file_base64, target_name=target_name, set_active=True)
        except ValueError as err:
            return self._invalid_input(str(err))
        result['character_card'] = load_character_card_meta()
        result['web'] = web_runtime_settings()
        return self._send(200, result)

    def _post_character_profile_override(self, parsed, payload):
        override = payload.get('override')
        if not isinstance(override, dict):
            return self._invalid_input('override must be an object')
        try:
            override = validate_unified_player_profile(override)
        except ValueError as err:
            return self._invalid_input(str(err))
        source_text = str(payload.get('source_text', '') or '')
        path = save_character_player_profile_override(override)
        save_character_player_profile_override_source(source_text)
        return self._send(200, {
            'ok': True,
            'path': path.name,
            'override': load_character_player_profile_override(),
            'source_text': read_profile_source(character_player_profile_override_source_path()),
            'prompt_preview': render_runtime_player_profile_markdown(load_character_player_profile_override()),
            'character_card': load_character_card_meta(),
            'web': web_runtime_settings(),
        })

    def _post_profile_normalize(self, parsed, payload):
        source_text = str(payload.get('source_text', '') or '')
        existing = payload.get('profile') if parsed.path == '/api/user-profile/normalize' else payload.get('override')
        if existing is not None and not isinstance(existing, dict):
            return self._invalid_input('existing profile must be an object')
        try:
            profile, diagnostics = normalize_profile_text_with_keeper_llm(source_text, existing_profile=existing if isinstance(existing, dict) else None)
        except Exception as err:
            return self._invalid_input(f'profile normalization failed: {err}')
        return self._send(200, {
            'profile': profile,
            'override': profile,
            'prompt_preview': render_runtime_player_profile_markdown(profile),
            'diagnostics': diagnostics,
            'web': web_runtime_settings(),
        })

    def _post_profile_preview(self, parsed, payload):
        profile = payload.get('profile') if parsed.path == '/api/user-profile/preview' else payload.get('override')
        if not isinstance(profile, dict):
            return self._invalid_input('profile must be an object')
        try:
            profile = validate_unified_player_profile(profile)
        except ValueError as err:
            return self._invalid_input(str(err))
        return self._send(200, {
            'prompt_preview': render_runtime_player_profile_markdown(profile),
            'web': web_runtime_settings(),
        })

    def _post_user_profile(self, parsed, payload):
        profile = payload.get('profile')
        if not isinstance(profile, dict):
            return self._invalid_input('profile must be an object')
        try:
            profile = validate_unified_player_profile(profile)
        except ValueError as err:
            return self._invalid_input(str(err))
        source_text = str(payload.get('source_text', '') or '')
        path = save_base_player_profile(profile)
        save_base_player_profile_source(source_text)
        return self._send(200, {
            'ok': True,
            'path': path.name,
            'profile': load_base_player_profile(),
            'source_text': read_profile_source(base_player_profile_source_path()),
            'prompt_preview': render_runtime_player_profile_markdown(load_base_player_profile()),
            'avatar_url': '/user-avatar' if resolve_user_avatar_path() else None,
            'web': web_runtime_settings(),
        })

    def _post_user_avatar(self, parsed, payload):
        filename = str(payload.get('filename', '') or '').strip()
        file_base64 = str(payload.get('file_base64', '') or '').strip()
        if not filename or not file_base64:
            return self._invalid_input('filename and file_base64 are required')
        try:
            file_bytes = decode_base64_limited(file_base64, max_bytes=MAX_AVATAR_BYTES, label='avatar')
            path = save_user_avatar(filename, file_bytes)
        except ValueError as err:
            return self._invalid_input(str(err))
        except Exception as err:
            return self._invalid_input(f'invalid avatar payload: {err}')
        return self._send(200, {
            'ok': True,
            'path': path.name,
            'avatar_url': '/user-avatar',
            'web': web_runtime_settings(),
        })

    def _post_user_avatar_delete(self, parsed, payload):
        delete_user_avatar()
        return self._send(200, {
            'ok': True,
            'avatar_url': None,
            'web': web_runtime_settings(),
        })

    def _post_chat_preview(self, parsed, payload):
        content_b64 = str(payload.get('content_base64', '') or '').strip()
        if not content_b64:
            return self._invalid_input('content_base64 is required')
        try:
            content = decode_chat_import_content(content_b64)
            card_meta = load_character_card_meta()
            expected_name = card_meta.get('name', '') if card_meta else ''
            result = preview_chat_import(content, expected_character_name=expected_name)
        except Exception as err:
            return self._invalid_input(str(err))
        return self._send(200, result)

    def _post_chat_import(self, parsed, payload):
        content_b64 = str(payload.get('content_base64', '') or '').strip()
        filename = str(payload.get('filename', '') or 'imported.jsonl').strip()
        if not content_b64:
            return self._invalid_input('content_base64 is required')
        try:
            content = decode_chat_import_content(content_b64)
            card_meta = load_character_card_meta()
            expected_name = card_meta.get('name', '') if card_meta else None
            report = import_sillytavern_from_content(
                content, filename,
                character_id=active_character_id(),
                expected_character_name=expected_name,
            )
        except (ValueError, UnicodeDecodeError, RuntimeError) as err:
            return self._invalid_input(str(err))
        sessions = list_sessions()
        return self._send(200, {'report': report, 'sessions': sessions})

    def _post_providers(self, parsed, payload):
        try:
            result = upsert_provider_config(payload)
        except SiteConfigPermissionError:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可修改站点设置'}})
        except ValueError as err:
            return self._invalid_input(str(err))
        result['supported_api_types'] = list_provider_configs()['supported_api_types']
        return self._send(200, result)

    def _post_site_config(self, parsed, payload):
        try:
            result = update_site_config(payload)
        except SiteConfigPermissionError:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可修改站点设置'}})
        except ValueError as err:
            return self._invalid_input(str(err))
        result['supported_api_types'] = list_provider_configs()['supported_api_types']
        return self._send(200, result)

    def _post_model_config(self, parsed, payload):
        try:
            result = update_model_config(payload)
        except ValueError as err:
            return self._invalid_input(str(err))
        return self._send(200, result)

    def _post_narrator_preset(self, parsed, payload):
        action = str(payload.get('action', 'save') or 'save').strip()
        preset_id = str(payload.get('preset_id') or payload.get('id') or '').strip()
        try:
            if action == 'delete':
                return self._send(200, delete_narrator_preset(preset_id))
            if action == 'save':
                content = payload.get('content')
                if not isinstance(content, dict):
                    raise ValueError('preset content must be an object')
                return self._send(200, save_narrator_preset(preset_id, content))
        except ValueError as err:
            return self._invalid_input(str(err))
        return self._invalid_input('unsupported narrator preset action')

    def _post_providers_discover(self, parsed, payload):
        try:
            result = discover_provider_models(str(payload.get('name', '') or ''))
        except SiteConfigPermissionError:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可探测站点模型'}})
        except ValueError as err:
            return self._invalid_input(str(err))
        result['supported_api_types'] = list_provider_configs()['supported_api_types']
        return self._send(200, result)

    def _post_site_models_discover(self, parsed, payload):
        try:
            result = discover_site_models()
        except SiteConfigPermissionError:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可探测站点模型'}})
        except ValueError as err:
            return self._invalid_input(str(err))
        result['supported_api_types'] = list_provider_configs()['supported_api_types']
        return self._send(200, result)

    def _post_auth_login(self, parsed, payload):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('multi-user login'))
        uid = self._payload_string(payload, 'user_id')
        pwd = self._payload_string(payload, 'password')
        if uid is None or pwd is None:
            return
        if not check_login_throttle(self.client_address[0] if self.client_address else ''):
            return self._send(429, {'error': {'code': 'RATE_LIMITED', 'message': '登录请求过于频繁，请稍后再试'}})
        try:
            token = login(uid, pwd)
        except ValueError as err:
            return self._send(401, {'error': {'code': 'AUTH_FAILED', 'message': str(err)}})
        return self._send(200, {'token': token, 'user_id': uid}, extra_headers={'Set-Cookie': auth_cookie_header(token)})

    def _post_auth_logout(self, parsed, payload):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('multi-user logout'))
        token = self._extract_token()
        if token:
            logout(token)
        return self._send(200, {'ok': True}, extra_headers={'Set-Cookie': clear_auth_cookie_header()})

    def _post_auth_change_password(self, parsed, payload):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('change-password'))
        token = self._extract_token()
        # POST already rejected Cookie auth, but require a valid Bearer
        # token here so unauthenticated callers cannot probe other
        # users' passwords.
        acting_uid = validate_token(token) if token else None
        if not acting_uid and not is_multi_user_enabled():
            acting_uid = DEFAULT_USER_ID
        if not acting_uid:
            return self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': '请先登录'}})
        old_pwd = payload.get('old_password')
        if old_pwd is None:
            old_pwd = ''
        if not isinstance(old_pwd, str):
            return self._invalid_input('old_password must be a string')
        new_pwd = self._payload_string(payload, 'new_password')
        if new_pwd is None:
            return
        try:
            change_own_password(acting_uid, old_pwd, new_pwd, keep_token=token)
        except ValueError as err:
            return self._invalid_input(str(err))
        return self._send(200, {'ok': True})

    def _post_users(self, parsed, payload):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('multi-user management'))
        try:
            action = payload_string(payload, 'action')
        except ValueError as err:
            return self._invalid_input(str(err))
        caller = self._authenticated_admin_user()
        bootstrap_admin_password = is_admin_password_bootstrap_action(action)
        if bootstrap_admin_password and not is_loopback_client(self.client_address[0]):
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '管理员密码首次设置只允许从本机访问'}})
        if caller != DEFAULT_USER_ID and not bootstrap_admin_password:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可管理用户'}})
        if action == 'create':
            uid = self._payload_string(payload, 'user_id')
            pwd = self._payload_string(payload, 'password')
            if uid is None or pwd is None:
                return
            try:
                result = create_user(uid, pwd)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, result)
        elif action == 'delete':
            uid = self._payload_string(payload, 'user_id')
            if uid is None:
                return
            try:
                delete_user(uid)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, {'ok': True})
        elif action == 'archive_orphan_dir':
            uid = self._payload_string(payload, 'user_id')
            if uid is None:
                return
            try:
                result = archive_orphan_user_dir(uid)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, result)
        elif action == 'disable':
            uid = self._payload_string(payload, 'user_id')
            if uid is None:
                return
            try:
                disable_user(uid, str(payload.get('reason', '') or ''))
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, {'ok': True})
        elif action == 'enable':
            uid = self._payload_string(payload, 'user_id')
            if uid is None:
                return
            try:
                enable_user(uid)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, {'ok': True})
        elif action == 'set_admin_password':
            pwd = self._payload_string(payload, 'password')
            if pwd is None:
                return
            try:
                set_admin_password(pwd)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, {'ok': True})
        elif action == 'reset_password':
            uid = self._payload_string(payload, 'user_id')
            pwd = self._payload_string(payload, 'password')
            if uid is None or pwd is None:
                return
            try:
                reset_user_password(uid, pwd)
            except ValueError as err:
                return self._invalid_input(str(err))
            return self._send(200, {'ok': True})
        else:
            return self._invalid_input('未知操作，支持: create, disable, enable, delete, archive_orphan_dir, reset_password, set_admin_password')

    def _post_multi_user(self, parsed, payload):
        if not MULTI_USER_PRODUCT_ENABLED:
            return self._send(403, _experimental_disabled_payload('multi-user mode toggle'))
        caller = self._authenticated_admin_user()
        if caller != DEFAULT_USER_ID:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可操作'}})
        try:
            enabled = payload_bool(payload, 'enabled')
        except ValueError as err:
            return self._invalid_input(str(err))
        password = self._payload_string(payload, 'password')
        if password is None:
            return
        try:
            login(DEFAULT_USER_ID, password)
        except ValueError:
            return self._send(401, {'error': {'code': 'AUTH_FAILED', 'message': '管理员密码错误'}})
        try:
            set_multi_user_enabled(enabled)
        except ValueError as err:
            return self._invalid_input(str(err))
        return self._send(200, {'multi_user_enabled': enabled})

    _POST_ROUTES = {
        '/api/new-game': _post_new_game,
        '/api/delete-session': _post_delete_session,
        '/api/regenerate-last': _post_regenerate_last,
        '/api/delete-latest-turn': _post_delete_latest_turn,
        '/api/message': _post_message,
        '/api/session-audit': _post_session_audit,
        '/api/character/select': _post_character_select,
        '/api/character/delete': _post_character_delete,
        '/api/character/rebuild-lorebook': _post_character_rebuild_lorebook,
        '/api/characters/import': _post_characters_import,
        '/api/character/profile-override': _post_character_profile_override,
        '/api/characters/profile-override': _post_character_profile_override,
        '/api/user-profile/normalize': _post_profile_normalize,
        '/api/character/profile-override/normalize': _post_profile_normalize,
        '/api/user-profile/preview': _post_profile_preview,
        '/api/character/profile-override/preview': _post_profile_preview,
        '/api/user-profile': _post_user_profile,
        '/api/user-avatar': _post_user_avatar,
        '/api/user-avatar/delete': _post_user_avatar_delete,
        '/api/chat/preview': _post_chat_preview,
        '/api/chat/import': _post_chat_import,
        '/api/providers': _post_providers,
        '/api/site-config': _post_site_config,
        '/api/model-config': _post_model_config,
        '/api/narrator-preset': _post_narrator_preset,
        '/api/providers/discover': _post_providers_discover,
        '/api/site-models/discover': _post_site_models_discover,
        '/api/auth/login': _post_auth_login,
        '/api/auth/logout': _post_auth_logout,
        '/api/auth/change-password': _post_auth_change_password,
        '/api/users': _post_users,
        '/api/multi-user': _post_multi_user,
    }

    def do_DELETE(self):
        with self._request_scope('DELETE') as (parsed, authorized):
            if not authorized:
                return
            payload = self._read_json_payload()
            if payload is None:
                return
            if business_payload_has_user_id(parsed.path, payload):
                return self._invalid_input('business API must not include user_id')
            try:
                handler = self._DELETE_ROUTES.get(parsed.path)
                if handler is None:
                    return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
                return handler(self, parsed, payload)
            except Exception as err:
                return self._handle_exception(err, route=parsed.path)

    def _delete_providers(self, parsed, payload):
        try:
            result = delete_provider_config(str(payload.get('name', '') or ''))
        except SiteConfigPermissionError as err:
            return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': str(err)}})
        except ValueError as err:
            return self._invalid_input(str(err))
        result['supported_api_types'] = list_provider_configs()['supported_api_types']
        return self._send(200, result)

    _DELETE_ROUTES = {
        '/api/providers': _delete_providers,
    }


def main():
    startup_security_check()
    try:
        server = RuntimeHTTPServer((HOST, PORT), Handler)
    except OSError as err:
        logger.error('Failed to bind threadloom backend on http://%s:%s: %s', HOST, PORT, err)
        raise SystemExit(1) from err

    logger.info('Threadloom backend listening on http://%s:%s', HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Threadloom backend interrupted, shutting down')
    finally:
        server.server_close()
        logger.info('Threadloom backend stopped')


if __name__ == '__main__':
    main()
