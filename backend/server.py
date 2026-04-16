#!/usr/bin/env python3
import errno
import json
import logging
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bootstrap_session import bootstrap_session
from character_manager import import_character_card_base64, list_character_cards, set_active_character
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
from paths import normalize_session_id, resolve_session_dir
from runtime_store import build_entity_map, build_state_snapshot, load_character_card_meta, load_history, load_state, resolve_character_cover_path, web_runtime_settings
from user_manager import (
    create_user, delete_user, list_users, login, logout,
    is_multi_user_enabled, set_multi_user_enabled,
    set_admin_password, resolve_user_from_request, ensure_admin_exists,
)


HOST = '127.0.0.1'
PORT = 8765
SESSION_LOCKS: dict[str, threading.Lock] = {}
SESSION_LOCKS_GUARD = threading.Lock()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('threadloom.server')


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
                return self._send(200, {
                    'users': list_users(),
                    'multi_user_enabled': is_multi_user_enabled(),
                })

            if parsed.path == '/api/auth/me':
                uid = resolve_user_from_request(dict(self.headers))
                return self._send(200, {'user_id': uid, 'multi_user_enabled': is_multi_user_enabled()})

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

            if parsed.path == '/api/chat/preview':
                import base64 as b64
                content_b64 = str(payload.get('content_base64', '') or '').strip()
                if not content_b64:
                    return self._invalid_input('content_base64 is required')
                try:
                    content = b64.b64decode(content_b64).decode('utf-8')
                    from paths import active_character_id
                    from character_manager import load_character_card_meta
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
                    from paths import active_character_id
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
                uid = str(payload.get('user_id', '') or '').strip()
                pwd = str(payload.get('password', '') or '')
                try:
                    token = login(uid, pwd)
                except ValueError as err:
                    return self._send(401, {'error': {'code': 'AUTH_FAILED', 'message': str(err)}})
                return self._send(200, {'token': token, 'user_id': uid})

            if parsed.path == '/api/auth/logout':
                token = self._extract_token()
                if token:
                    logout(token)
                return self._send(200, {'ok': True})

            if parsed.path == '/api/users':
                caller = resolve_user_from_request(dict(self.headers))
                from paths import DEFAULT_USER_ID as _ADMIN
                if caller != _ADMIN:
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
                caller = resolve_user_from_request(dict(self.headers))
                from paths import DEFAULT_USER_ID as _ADMIN
                if caller != _ADMIN:
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
