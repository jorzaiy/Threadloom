#!/usr/bin/env python3
import json
import logging
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bootstrap_session import bootstrap_session
from handler_message import handle_message
from regenerate_turn import regenerate_last_partial
from session_lifecycle import delete_session, list_sessions, start_new_game
from runtime_store import build_entity_map, build_state_snapshot, load_character_card_meta, load_history, load_state, resolve_character_cover_path, web_runtime_settings


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

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args):
        logger.info('%s - %s', self.address_string(), format % args)

    def _handle_exception(self, err: Exception, *, route: str):
        logger.exception('Unhandled request error on %s: %s', route, err)
        return self._send(500, {'error': {'code': 'INTERNAL_ERROR', 'message': 'internal server error'}})

    def _session_lock(self, session_id: str) -> threading.Lock:
        with SESSION_LOCKS_GUARD:
            lock = SESSION_LOCKS.get(session_id)
            if lock is None:
                lock = threading.Lock()
                SESSION_LOCKS[session_id] = lock
            return lock

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        session_id = (qs.get('session_id') or [''])[0].strip()

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
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                bootstrap_session(session_id)
                state = load_state(session_id)
                return self._send(200, {
                    'session_id': session_id,
                    'state': build_state_snapshot(state),
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/sessions':
                sessions = list_sessions()
                default_session_id = next((item['session_id'] for item in sessions if not item.get('archived') and not item.get('replay')), 'story-live')
                return self._send(200, {
                    'sessions': sessions,
                    'default_session_id': default_session_id,
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/history':
                if not session_id:
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                bootstrap_session(session_id)
                page_size = web_runtime_settings().get('history_page_size', 80)
                messages = load_history(session_id)[-page_size:]
                return self._send(200, {
                    'session_id': session_id,
                    'messages': messages,
                    'character_card': load_character_card_meta(),
                    'web': web_runtime_settings(),
                })

            if parsed.path == '/api/entity':
                entity_id = (qs.get('entity_id') or [''])[0].strip()
                if not session_id or not entity_id:
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id and entity_id are required'}})
                bootstrap_session(session_id)
                state = load_state(session_id)
                entities = build_entity_map(state, session_id=session_id)
                entity = entities.get(entity_id)
                if not entity:
                    return self._send(404, {'error': {'code': 'ENTITY_NOT_FOUND', 'message': 'entity not found'}})
                return self._send(200, {'session_id': session_id, 'entity': entity})

            if parsed.path in {'/', '/index.html'}:
                index_path = Path(__file__).resolve().parents[1] / 'frontend' / 'index.html'
                body = index_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == '/app.js':
                app_path = Path(__file__).resolve().parents[1] / 'frontend' / 'app.js'
                body = app_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == '/styles.css':
                css_path = Path(__file__).resolve().parents[1] / 'frontend' / 'styles.css'
                body = css_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/css; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == '/favicon.svg':
                icon_path = Path(__file__).resolve().parents[1] / 'frontend' / 'favicon.svg'
                if icon_path.exists():
                    body = icon_path.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/svg+xml')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

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
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

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
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                with self._session_lock(session_id):
                    return self._send(200, start_new_game(session_id))

            if parsed.path == '/api/delete-session':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                with self._session_lock(session_id):
                    return self._send(200, delete_session(session_id))

            if parsed.path == '/api/regenerate-last':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                with self._session_lock(session_id):
                    result = regenerate_last_partial(session_id)
                status = 200 if 'error' not in result else 400
                return self._send(status, result)

            if parsed.path == '/api/message':
                session_id = str(payload.get('session_id', '') or '').strip()
                if not session_id:
                    return self._send(400, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}})
                with self._session_lock(session_id):
                    result = handle_message(payload)
                status = 200 if 'error' not in result else 400
                return self._send(status, result)

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
