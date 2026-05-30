"""Routing-layer guard for backend/server.py.

server.py historically had no unit coverage. When the giant do_GET/do_POST/
do_DELETE if-chains were converted to dispatch tables, the risk was silently
dropping, renaming, or mis-wiring a route. These tests pin the exact route set
per verb and exercise the shared request helpers so that regression shows up as
a failing assertion instead of a 404 in production.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import server  # noqa: E402
from server import Handler  # noqa: E402


EXPECTED_GET = {
    '/api/health', '/api/state', '/api/sessions', '/api/providers', '/api/characters',
    '/api/user-profile', '/api/character/profile-override', '/user-avatar', '/api/site-config',
    '/api/model-config', '/api/narrator-preset', '/api/users', '/api/auth/me', '/api/history',
    '/api/entity', '/', '/index.html', '/app.js', '/login.js', '/marked.min.js', '/styles.css',
    '/favicon.svg', '/character-cover',
}

EXPECTED_POST = {
    '/api/new-game', '/api/delete-session', '/api/regenerate-last', '/api/delete-latest-turn',
    '/api/message', '/api/session-audit', '/api/character/select', '/api/character/delete',
    '/api/character/rebuild-lorebook', '/api/characters/import', '/api/character/profile-override',
    '/api/characters/profile-override', '/api/user-profile/normalize',
    '/api/character/profile-override/normalize', '/api/user-profile/preview',
    '/api/character/profile-override/preview', '/api/user-profile', '/api/user-avatar',
    '/api/user-avatar/delete', '/api/chat/preview', '/api/chat/import', '/api/providers',
    '/api/site-config', '/api/model-config', '/api/narrator-preset', '/api/providers/discover',
    '/api/site-models/discover', '/api/auth/login', '/api/auth/logout',
    '/api/auth/change-password', '/api/users', '/api/multi-user',
}

EXPECTED_DELETE = {'/api/providers'}


class RouteTableTests(unittest.TestCase):
    def test_get_routes_cover_exactly_the_documented_paths(self):
        self.assertEqual(set(Handler._GET_ROUTES), EXPECTED_GET)

    def test_post_routes_cover_exactly_the_documented_paths(self):
        self.assertEqual(set(Handler._POST_ROUTES), EXPECTED_POST)

    def test_delete_routes_cover_exactly_the_documented_paths(self):
        self.assertEqual(set(Handler._DELETE_ROUTES), EXPECTED_DELETE)

    def test_all_route_handlers_are_callable(self):
        for table in (Handler._GET_ROUTES, Handler._POST_ROUTES, Handler._DELETE_ROUTES):
            for path, handler in table.items():
                self.assertTrue(callable(handler), path)

    def test_shared_handlers_are_actually_shared(self):
        # Path aliases that previously shared one if-block body must resolve to
        # the same handler object.
        self.assertIs(Handler._GET_ROUTES['/'], Handler._GET_ROUTES['/index.html'])
        self.assertIs(
            Handler._POST_ROUTES['/api/character/profile-override'],
            Handler._POST_ROUTES['/api/characters/profile-override'],
        )
        self.assertIs(
            Handler._POST_ROUTES['/api/user-profile/normalize'],
            Handler._POST_ROUTES['/api/character/profile-override/normalize'],
        )
        self.assertIs(
            Handler._POST_ROUTES['/api/user-profile/preview'],
            Handler._POST_ROUTES['/api/character/profile-override/preview'],
        )


class _StubHandler(Handler):
    # Build a Handler without BaseHTTPRequestHandler.__init__ (which needs a
    # live socket). We only exercise routing/helper logic, capturing responses.
    def __init__(self):
        self.sent = []

    def _send(self, status, payload, *, extra_headers=None):
        self.sent.append((status, payload))
        return True

    def _invalid_input(self, message):
        self.sent.append((400, {'error': {'code': 'INVALID_INPUT', 'message': message}}))
        return True


class ScopedSessionHelperTests(unittest.TestCase):
    def test_rejects_empty_session_id(self):
        h = _StubHandler()
        self.assertIsNone(h._resolve_scoped_session('', allow_missing=True))
        self.assertEqual(h.sent[-1][0], 400)
        self.assertIn('session_id is required', h.sent[-1][1]['error']['message'])

    def test_returns_normalized_id_when_scope_ok(self):
        h = _StubHandler()
        h._validate_active_session_scope = lambda session_id, allow_missing=False: True
        original = server.normalize_session_id
        server.normalize_session_id = lambda value: value
        try:
            out = h._resolve_scoped_session('sess-001', allow_missing=True)
        finally:
            server.normalize_session_id = original
        self.assertEqual(out, 'sess-001')
        self.assertEqual(h.sent, [])  # nothing sent on the success path

    def test_returns_none_when_scope_check_fails(self):
        h = _StubHandler()
        # _validate_active_session_scope sends its own 404/409 and returns False.
        h._validate_active_session_scope = lambda session_id, allow_missing=False: False
        original = server.normalize_session_id
        server.normalize_session_id = lambda value: value
        try:
            self.assertIsNone(h._resolve_scoped_session('sess-001', allow_missing=False))
        finally:
            server.normalize_session_id = original


class DispatchedHandlerTests(unittest.TestCase):
    def test_health_handler_sends_service_payload(self):
        h = _StubHandler()
        h._get_health(None, {})
        self.assertEqual(h.sent[-1][0], 200)
        self.assertEqual(h.sent[-1][1]['service'], 'threadloom-backend')


if __name__ == '__main__':
    unittest.main()
