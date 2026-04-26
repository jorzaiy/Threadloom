#!/usr/bin/env python3
import errno
import json
import logging
import threading
import sys
from base64 import b64decode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bootstrap_session import bootstrap_session
from character_manager import delete_character_card, import_character_card_base64, list_character_cards, rebuild_character_lorebook, set_active_character
from handler_message import handle_message
from import_sillytavern_chat import import_sillytavern_from_content, preview_chat_import
from model_config import (
    delete_provider_config,
    discover_provider_models,
    discover_site_models,
    get_model_config_snapshot,
    get_site_config_snapshot,
    list_provider_configs,
    update_model_config,
    update_site_config,
    upsert_provider_config,
)
from regenerate_turn import regenerate_last_partial
from session_lifecycle import delete_session, list_sessions, start_new_game
from paths import DEFAULT_USER_ID, active_character_id, normalize_session_id, resolve_session_dir
from player_profile import delete_user_avatar, load_base_player_profile, load_character_player_profile_override, resolve_user_avatar_path, save_base_player_profile, save_character_player_profile_override, save_user_avatar
from runtime_store import build_entity_map, build_state_snapshot, load_character_card_meta, load_history, load_state, resolve_character_cover_path, web_runtime_settings
from user_manager import (
    create_user, delete_user, list_users, login, logout,
    is_multi_user_enabled, set_multi_user_enabled,
    set_admin_password, resolve_user_from_request, ensure_admin_exists,
)


HOST = '0.0.0.0'
PORT = 8765
SESSION_LOCKS: dict[str, threading.Lock] = {}
SESSION_LOCKS_GUARD = threading.Lock()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('threadloom.server')
MULTI_USER_PRODUCT_ENABLED = False


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
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
            return True
        except Exception as err:
            if self._is_client_disconnect(err):
                logger.info('Client disconnected before response could be sent on %s', self.path)
                return False
            raise

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
            lock = SESSION_LOCKS.get(session_id)
            if lock is None:
                lock = threading.Lock()
                SESSION_LOCKS[session_id] = lock
            return lock

    def _extract_token(self) -> str:
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            part = part.strip()
            if part.startswith('session_token='):
                return part[len('session_token='):]
        return ''

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
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
                return self._send_raw(200, avatar_path.read_bytes(), content_type=content_type)

            if parsed.path == '/api/site-config':
                payload = get_site_config_snapshot()
                payload['supported_api_types'] = list_provider_configs()['supported_api_types']
                payload['web'] = web_runtime_settings()
                return self._send(200, payload)

            if parsed.path == '/api/model-config':
                payload = get_model_config_snapshot()
                payload['web'] = web_runtime_settings()
                return self._send(200, payload)

            if parsed.path == '/api/users':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user management'))
                caller = resolve_user_from_request(dict(self.headers))
                if caller != DEFAULT_USER_ID:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可查看用户列表'}})
                return self._send(200, {
                    'users': list_users(),
                    'multi_user_enabled': is_multi_user_enabled(),
                })

            if parsed.path == '/api/auth/me':
                uid = resolve_user_from_request(dict(self.headers))
                if is_multi_user_enabled() and uid is None:
                    return self._send(401, {'error': {'code': 'AUTH_REQUIRED', 'message': 'login required'}})
                return self._send(200, {'user_id': uid or '', 'multi_user_enabled': is_multi_user_enabled()})

            if parsed.path == '/api/history':
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
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
                all_messages = load_history(session_id)
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
                        extra_headers={'Cache-Control': 'public, max-age=3600'},
                    )

            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
        except Exception as err:
            return self._handle_exception(err, route=parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'invalid json'}})

        try:
            if parsed.path == '/api/new-game':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._invalid_input('session_id is required')
                try:
                    session_id = normalize_session_id(session_id)
                except ValueError as err:
                    return self._invalid_input(str(err))
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

            if parsed.path == '/api/characters/profile-override':
                override = payload.get('override')
                if not isinstance(override, dict):
                    return self._invalid_input('override must be an object')
                path = save_character_player_profile_override(override)
                return self._send(200, {
                    'ok': True,
                    'path': str(path),
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
                    'path': str(path),
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
                    file_bytes = b64decode(file_base64.encode('utf-8'), validate=True)
                    path = save_user_avatar(filename, file_bytes)
                except ValueError as err:
                    return self._invalid_input(str(err))
                except Exception as err:
                    return self._invalid_input(f'invalid avatar payload: {err}')
                return self._send(200, {
                    'ok': True,
                    'path': str(path),
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
                import base64 as b64
                content_b64 = str(payload.get('content_base64', '') or '').strip()
                if not content_b64:
                    return self._invalid_input('content_base64 is required')
                try:
                    content = b64.b64decode(content_b64).decode('utf-8')
                    card_meta = load_character_card_meta()
                    expected_name = card_meta.get('name', '') if card_meta else ''
                    result = preview_chat_import(content, expected_character_name=expected_name)
                except Exception as err:
                    return self._invalid_input(str(err))
                return self._send(200, result)

            if parsed.path == '/api/chat/import':
                import base64 as b64
                content_b64 = str(payload.get('content_base64', '') or '').strip()
                filename = str(payload.get('filename', '') or 'imported.jsonl').strip()
                if not content_b64:
                    return self._invalid_input('content_base64 is required')
                try:
                    content = b64.b64decode(content_b64).decode('utf-8')
                    card_meta = load_character_card_meta()
                    expected_name = card_meta.get('name', '') if card_meta else None
                    report = import_sillytavern_from_content(
                        content, filename,
                        character_id=active_character_id(),
                        expected_character_name=expected_name,
                    )
                except RuntimeError as err:
                    return self._invalid_input(str(err))
                sessions = list_sessions()
                return self._send(200, {'report': report, 'sessions': sessions['sessions']})

            if parsed.path == '/api/providers':
                try:
                    result = upsert_provider_config(payload)
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            if parsed.path == '/api/site-config':
                try:
                    result = update_site_config(payload)
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

            if parsed.path == '/api/providers/discover':
                try:
                    result = discover_provider_models(str(payload.get('name', '') or ''))
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            if parsed.path == '/api/site-models/discover':
                try:
                    result = discover_site_models()
                except ValueError as err:
                    return self._invalid_input(str(err))
                result['supported_api_types'] = list_provider_configs()['supported_api_types']
                return self._send(200, result)

            # ── 用户管理 API ──
            if parsed.path == '/api/auth/login':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user login'))
                uid = str(payload.get('user_id', '') or '').strip()
                pwd = str(payload.get('password', '') or '')
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

            if parsed.path == '/api/users':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user management'))
                caller = resolve_user_from_request(dict(self.headers))
                if caller != DEFAULT_USER_ID:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可管理用户'}})
                action = str(payload.get('action', '') or '').strip()
                if action == 'create':
                    uid = str(payload.get('user_id', '') or '').strip()
                    pwd = str(payload.get('password', '') or '')
                    try:
                        result = create_user(uid, pwd)
                    except ValueError as err:
                        return self._invalid_input(str(err))
                    return self._send(200, result)
                elif action == 'delete':
                    uid = str(payload.get('user_id', '') or '').strip()
                    try:
                        delete_user(uid)
                    except ValueError as err:
                        return self._invalid_input(str(err))
                    return self._send(200, {'ok': True})
                elif action == 'set_admin_password':
                    pwd = str(payload.get('password', '') or '')
                    if not pwd:
                        return self._invalid_input('密码不能为空')
                    set_admin_password(pwd)
                    return self._send(200, {'ok': True})
                else:
                    return self._invalid_input('未知操作，支持: create, delete, set_admin_password')

            if parsed.path == '/api/multi-user':
                if not MULTI_USER_PRODUCT_ENABLED:
                    return self._send(403, _experimental_disabled_payload('multi-user mode toggle'))
                caller = resolve_user_from_request(dict(self.headers))
                if caller != DEFAULT_USER_ID:
                    return self._send(403, {'error': {'code': 'FORBIDDEN', 'message': '仅管理员可操作'}})
                enabled = bool(payload.get('enabled', False))
                set_multi_user_enabled(enabled)
                return self._send(200, {'multi_user_enabled': enabled})

            return self._send(404, {'error': {'code': 'NOT_FOUND', 'message': 'unknown route'}})
        except Exception as err:
            return self._handle_exception(err, route=parsed.path)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            return self._invalid_input('invalid json')

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


def main():
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
