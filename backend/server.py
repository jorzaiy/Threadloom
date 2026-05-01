#!/usr/bin/env python3
import errno
import json
import logging
import os
import threading
import time
import sys
import weakref
from base64 import b64decode
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
from regenerate_turn import regenerate_last_partial
from session_lifecycle import delete_session, list_sessions, start_new_game
from paths import DEFAULT_USER_ID, active_character_id, active_user_id, current_session_dir, find_character_session_dir, is_path_within_user_root, normalize_session_id, resolve_session_dir, reset_active_user_id, reset_multi_user_request_context, set_active_user_id, set_multi_user_request_context, slugify
from player_profile import delete_user_avatar, load_base_player_profile, load_character_player_profile_override, resolve_user_avatar_path, save_base_player_profile, save_character_player_profile_override, save_user_avatar
from runtime_store import build_entity_map, build_state_snapshot, filter_committed_history_items, load_character_card_meta, load_history, load_state, resolve_character_cover_path, web_runtime_settings
from user_manager import (
    admin_has_password, change_own_password, create_user, delete_user, disable_user, enable_user,
    list_user_storage_audit, list_users, login, logout,
    is_multi_user_enabled, set_multi_user_enabled,
    reset_user_password, set_admin_password, resolve_user_from_request, validate_token,
)


HOST = '127.0.0.1'
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
    '/app.js',
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
    if is_multi_user_enabled() and HOST not in {'127.0.0.1', 'localhost', '::1'}:
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
            headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; script-src 'self' https://cdn.jsdelivr.net; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
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

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return self._send_raw(
            status,
            body,
            content_type='application/json; charset=utf-8',
        )

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

    def _authenticated_admin_user(self) -> str | None:
        return authenticated_admin_from_token(self._extract_token())

    def _begin_request_user(self, path: str, method: str) -> tuple[str | None, Token[str] | None, bool]:
        uid, token, ok = begin_request_user_context(path, method, dict(self.headers))
        if not ok:
            self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': 'login required'}})
            return None, None, False
        return uid, token, True

    def do_GET(self):
        parsed = urlparse(self.path)
        _, user_token, authorized = self._begin_request_user(parsed.path, 'GET')
        multi_user_token = begin_multi_user_request_context() if authorized else None
        if not authorized:
            return
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if business_query_has_user_id(parsed.path, qs):
            self._invalid_input('business API must not include user_id')
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)
            return
        session_id = (qs.get('session_id') or [''])[0].strip()
        before_raw = (qs.get('before') or [''])[0].strip()

        try:
            if parsed.path == '/api/health':
                return self._send(200, {
                    'ok': True,
                    'service': 'threadloom-backend',
                    'host': HOST,
                    'port': PORT,
                })

            if parsed.path == '/api/state':
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=True):
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

            if parsed.path == '/api/sessions':
                sessions = list_sessions()
                default_session_id = next((item['session_id'] for item in sessions if not item.get('archived') and not item.get('replay')), '')
                return self._send(200, {
                    'sessions': sessions,
                    'default_session_id': default_session_id,
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/providers':
                payload = list_provider_configs()
                payload['web'] = web_runtime_settings()
                return self._send(200, payload)

            if parsed.path == '/api/characters':
                return self._send(200, {
                    'characters': list_character_cards(),
                    'active_character_id': load_character_card_meta().get('character_id', ''),
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/user-profile':
                profile = load_base_player_profile()
                return self._send(200, {
                    'profile': profile,
                    'avatar_url': '/user-avatar' if resolve_user_avatar_path() else None,
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/character/profile-override':
                return self._send(200, {
                    'override': load_character_player_profile_override(),
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/user-avatar':
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

            if parsed.path == '/api/site-config':
                payload = get_site_config_snapshot()
                if active_user_id() != DEFAULT_USER_ID:
                    payload.pop('api_key_masked', None)
                    payload.pop('api_key_reference', None)
                payload['supported_api_types'] = list_provider_configs()['supported_api_types']
                payload['web'] = web_runtime_settings()
                return self._send(200, payload)

            if parsed.path == '/api/model-config':
                payload = get_model_config_snapshot()
                payload['web'] = web_runtime_settings()
                return self._send(200, payload)

            if parsed.path == '/api/narrator-preset':
                preset_id = (qs.get('preset_id') or qs.get('id') or [''])[0].strip()
                try:
                    return self._send(200, load_narrator_preset(preset_id))
                except ValueError as err:
                    return self._invalid_input(str(err))

            if parsed.path == '/api/users':
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

            if parsed.path == '/api/auth/me':
                uid = resolve_user_from_request(dict(self.headers))
                if is_multi_user_enabled() and uid is None:
                    return self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': 'login required'}})
                role = 'admin' if uid == DEFAULT_USER_ID else 'user'
                # admin_has_password lets the frontend know whether the
                # "enable multi-user" wizard needs to set a password first.
                return self._send(200, {
                    'user_id': uid or '',
                    'role': role,
                    'multi_user_enabled': is_multi_user_enabled(),
                    'admin_has_password': admin_has_password(),
                })

            if parsed.path == '/api/history':
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=True):
                    return
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

            if parsed.path == '/api/entity':
                entity_id = (qs.get('entity_id') or [''])[0].strip()
                if not session_id or not entity_id:
                    return self._invalid_input('session_id and entity_id are required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=False):
                    return
                if not self._session_exists(session_id):
                    return self._send(404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'session not found'}})
                state = load_state(session_id)
                entities = build_entity_map(state, session_id=session_id)
                entity = entities.get(entity_id)
                if not entity:
                    return self._send(404, {'error': {'code': 'ENTITY_NOT_FOUND', 'message': 'entity not found'}})
                return self._send(200, {'session_id': session_id, 'entity': entity})

            if parsed.path in {'/', '/index.html'}:
                index_path = Path(__file__).resolve().parents[1] / 'frontend' / 'index.html'
                body = index_path.read_bytes()
                return self._send_raw(200, body, content_type='text/html; charset=utf-8')

            if parsed.path == '/app.js':
                app_path = Path(__file__).resolve().parents[1] / 'frontend' / 'app.js'
                body = app_path.read_bytes()
                return self._send_raw(200, body, content_type='application/javascript; charset=utf-8')

            if parsed.path == '/styles.css':
                css_path = Path(__file__).resolve().parents[1] / 'frontend' / 'styles.css'
                body = css_path.read_bytes()
                return self._send_raw(200, body, content_type='text/css; charset=utf-8')

            if parsed.path == '/favicon.svg':
                icon_path = Path(__file__).resolve().parents[1] / 'frontend' / 'favicon.svg'
                if icon_path.exists():
                    body = icon_path.read_bytes()
                    return self._send_raw(200, body, content_type='image/svg+xml')

            if parsed.path == '/character-cover':
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

            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
        except Exception as err:
            return self._handle_exception(err, route=parsed.path)
        finally:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)

    def do_POST(self):
        parsed = urlparse(self.path)
        _, user_token, authorized = self._begin_request_user(parsed.path, 'POST')
        multi_user_token = begin_multi_user_request_context() if authorized else None
        if not authorized:
            return
        payload = self._read_json_payload()
        if payload is None:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)
            return
        if business_payload_has_user_id(parsed.path, payload):
            self._invalid_input('business API must not include user_id')
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)
            return

        try:
            if parsed.path == '/api/new-game':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=True):
                    return
                with self._session_lock(session_id):
                    return self._send(200, start_new_game(session_id))

            if parsed.path == '/api/delete-session':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=False):
                    return
                with self._session_lock(session_id):
                    return self._send(200, delete_session(session_id))

            if parsed.path == '/api/regenerate-last':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=False):
                    return
                with self._session_lock(session_id):
                    result = regenerate_last_partial(session_id)
                status = 200 if 'error' not in result else 400
                return self._send(status, result)

            if parsed.path == '/api/message':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
                if not self._validate_active_session_scope(session_id, allow_missing=True):
                    return
                payload['session_id'] = session_id
                with self._session_lock(session_id):
                    result = handle_message(payload)
                status = 200 if 'error' not in result else 400
                return self._send(status, result)

            if parsed.path == '/api/character/select':
                try:
                    result = set_active_character(str(payload.get('character_id', '') or ''))
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['character_card'] = load_character_card_meta()
                result['web'] = web_runtime_settings()
                return self._send(200, result)

            if parsed.path == '/api/character/delete':
                try:
                    result = delete_character_card(str(payload.get('character_id', '') or ''))
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['character_card'] = load_character_card_meta()
                result['web'] = web_runtime_settings()
                return self._send(200, result)

            if parsed.path == '/api/character/rebuild-lorebook':
                try:
                    result = rebuild_character_lorebook(str(payload.get('character_id', '') or ''))
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['character_card'] = load_character_card_meta()
                result['web'] = web_runtime_settings()
                return self._send(200, result)

            if parsed.path == '/api/characters/import':
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

            if parsed.path in {'/api/character/profile-override', '/api/characters/profile-override'}:
                override = payload.get('override')
                if not isinstance(override, dict):
                    return self._invalid_input('override must be an object')
                path = save_character_player_profile_override(override)
                return self._send(200, {
                    'ok': True,
                    'path': path.name,
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/user-profile':
                profile = payload.get('profile')
                if not isinstance(profile, dict):
                    return self._invalid_input('profile must be an object')
                path = save_base_player_profile(profile)
                return self._send(200, {
                    'ok': True,
                    'path': path.name,
                    'profile': load_base_player_profile(),
                    'avatar_url': '/user-avatar' if resolve_user_avatar_path() else None,
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/user-avatar':
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

            if parsed.path == '/api/user-avatar/delete':
                delete_user_avatar()
                return self._send(200, {
                    'ok': True,
                    'avatar_url': None,
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/chat/preview':
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

            if parsed.path == '/api/chat/import':
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

            if parsed.path == '/api/providers':
                try:
                    result = upsert_provider_config(payload)
                except SiteConfigPermissionError:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可修改站点设置'}})
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            if parsed.path == '/api/site-config':
                try:
                    result = update_site_config(payload)
                except SiteConfigPermissionError:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可修改站点设置'}})
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            if parsed.path == '/api/model-config':
                try:
                    result = update_model_config(payload)
                except ValueError as err:
                    return self._invalid_input(str(err))
                return self._send(200, result)

            if parsed.path == '/api/narrator-preset':
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

            if parsed.path == '/api/providers/discover':
                try:
                    result = discover_provider_models(str(payload.get('name', '') or ''))
                except SiteConfigPermissionError:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可探测站点模型'}})
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            if parsed.path == '/api/site-models/discover':
                try:
                    result = discover_site_models()
                except SiteConfigPermissionError:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可探测站点模型'}})
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            # ── 用户管理 API ──
            if parsed.path == '/api/auth/login':
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
                return self._send(200, {'token': token, 'user_id': uid})

            if parsed.path == '/api/auth/logout':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user logout'))
                token = self._extract_token()
                if token:
                    logout(token)
                return self._send(200, {'ok': True})

            if parsed.path == '/api/auth/change-password':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('change-password'))
                token = self._extract_token()
                # POST already rejected Cookie auth, but require a valid Bearer
                # token here so unauthenticated callers cannot probe other
                # users' passwords.
                acting_uid = validate_token(token) if token else None
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

            if parsed.path == '/api/users':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user management'))
                try:
                    action = payload_string(payload, 'action')
                except ValueError as err:
                    return self._invalid_input(str(err))
                caller = self._authenticated_admin_user()
                bootstrap_admin_password = is_admin_password_bootstrap_action(action)
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
                    return self._invalid_input('未知操作，支持: create, disable, enable, delete, reset_password, set_admin_password')

            if parsed.path == '/api/multi-user':
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

            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
        except Exception as err:
            return self._handle_exception(err, route=parsed.path)
        finally:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        _, user_token, authorized = self._begin_request_user(parsed.path, 'DELETE')
        multi_user_token = begin_multi_user_request_context() if authorized else None
        if not authorized:
            return
        payload = self._read_json_payload()
        if payload is None:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)
            return
        if business_payload_has_user_id(parsed.path, payload):
            self._invalid_input('business API must not include user_id')
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)
            return

        try:
            if parsed.path == '/api/providers':
                try:
                    result = delete_provider_config(str(payload.get('name', '') or ''))
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)
            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
        except Exception as err:
            return self._handle_exception(err, route=parsed.path)
        finally:
            if user_token is not None:
                reset_active_user_id(user_token)
            if multi_user_token is not None:
                reset_multi_user_request_context(multi_user_token)


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
