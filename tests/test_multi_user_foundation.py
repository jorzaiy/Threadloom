#!/usr/bin/env python3
import base64
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from io import BytesIO
from http.client import HTTPMessage

BACKEND_ROOT = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from backend import paths, user_manager

sys.modules['paths'] = paths
sys.modules['user_manager'] = user_manager

from backend import character_manager
from backend import character_assets
from backend import runtime_store
from backend import model_config
from backend import player_profile
from backend import server
from backend import session_lifecycle


class BusinessRejectHandler(server.Handler):
    payload: dict[str, object] = {}
    sent: tuple[int, dict[str, object]] | None = None

    def _read_json_payload(self):
        return self.payload

    def _send(self, status, payload):
        self.sent = (status, payload)
        return True


def make_business_reject_handler(payload: dict[str, object]) -> BusinessRejectHandler:
    handler = object.__new__(BusinessRejectHandler)
    handler.path = '/api/message'
    handler.headers = HTTPMessage()
    handler.payload = payload
    handler.sent = None
    handler.rfile = BytesIO()
    handler.wfile = BytesIO()
    return handler


def make_post_handler(path: str, payload: dict[str, object]) -> BusinessRejectHandler:
    handler = make_business_reject_handler(payload)
    handler.path = path
    handler.headers = HTTPMessage()
    handler.headers['Authorization'] = 'Bearer token'
    return handler


class CaptureGetHandler(server.Handler):
    sent: tuple[int, dict[str, object]] | None = None

    def _send(self, status, payload):
        self.sent = (status, payload)
        return True


def make_get_handler(path: str) -> CaptureGetHandler:
    handler = object.__new__(CaptureGetHandler)
    handler.path = path
    handler.headers = HTTPMessage()
    handler.sent = None
    handler.rfile = BytesIO()
    handler.wfile = BytesIO()
    return handler


class MultiUserFoundationTests(unittest.TestCase):
    def test_active_user_context_resets_after_scope(self):
        self.assertEqual(paths.active_user_id(), paths.DEFAULT_USER_ID)

        with paths.active_user_context('user-a'):
            self.assertEqual(paths.active_user_id(), 'user-a')
            self.assertEqual(paths.user_root(), paths.RUNTIME_DATA_ROOT / 'user-a')

        self.assertEqual(paths.active_user_id(), paths.DEFAULT_USER_ID)

    def test_normalize_user_id_rejects_reserved_and_path_values(self):
        self.assertEqual(paths.normalize_user_id('user-a_01'), 'user-a_01')
        for value in ('', '../user', 'a/b', 'a%2Fb', '_system', '_template', 'has space', '中文'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    paths.normalize_user_id(value)

    def test_confine_to_user_root_rejects_escape(self):
        root = paths.user_runtime_root('user-a')
        self.assertEqual(
            paths.confine_to_user_root(root / 'config' / 'site.json', 'user-a'),
            root / 'config' / 'site.json',
        )
        with self.assertRaises(ValueError):
            paths.confine_to_user_root(root.parent / 'user-b' / 'config' / 'site.json', 'user-a')

    def test_auth_sessions_store_token_hash_and_revoke_on_admin_password_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'

                user_manager.set_admin_password('secure-password-123')
                mode = stat.S_IMODE(user_manager.USERS_FILE.stat().st_mode)
                self.assertEqual(mode, 0o600)
                token = user_manager.login(paths.DEFAULT_USER_ID, 'secure-password-123')
                mode = stat.S_IMODE(user_manager.SESSIONS_FILE.stat().st_mode)
                self.assertEqual(mode, 0o600)
                sessions = json.loads(user_manager.SESSIONS_FILE.read_text(encoding='utf-8'))

                self.assertNotIn(token, sessions)
                self.assertEqual(user_manager.validate_token(token), paths.DEFAULT_USER_ID)
                session_entry = next(iter(sessions.values()))
                self.assertEqual(session_entry['user_id'], paths.DEFAULT_USER_ID)
                self.assertIn('expires_at', session_entry)
                self.assertIn('last_seen_at', session_entry)

                user_manager.set_admin_password('secure-password-456')
                self.assertIsNone(user_manager.validate_token(token))
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_validate_token_migrates_legacy_plaintext_session_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                user_manager._ensure_system_dir()
                legacy_token = 'legacy-token'
                user_manager.SESSIONS_FILE.write_text(
                    json.dumps({
                        legacy_token: {
                            'user_id': paths.DEFAULT_USER_ID,
                            'created_at': 2000000000,
                            'expires_at': 4102444800,
                        }
                    }),
                    encoding='utf-8',
                )

                self.assertEqual(user_manager.validate_token(legacy_token), paths.DEFAULT_USER_ID)
                sessions = json.loads(user_manager.SESSIONS_FILE.read_text(encoding='utf-8'))

                self.assertNotIn(legacy_token, sessions)
                self.assertEqual(len(sessions), 1)
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_enabling_multi_user_requires_admin_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'

                with self.assertRaises(ValueError):
                    user_manager.set_multi_user_enabled(True)

                user_manager.set_admin_password('secure-password-123')
                user_manager.set_multi_user_enabled(True)
                site_config = json.loads((temp_root / paths.DEFAULT_USER_ID / 'config' / 'site.json').read_text(encoding='utf-8'))
                self.assertTrue(site_config['multi_user_enabled'])
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_reset_user_password_revokes_sessions_and_list_users_returns_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_user_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            original_paths_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                paths.RUNTIME_DATA_ROOT = temp_root

                user_manager.create_user('user-a', 'secure-password-123')
                token = user_manager.login('user-a', 'secure-password-123')
                self.assertEqual(user_manager.validate_token(token), 'user-a')

                reset_user_password = getattr(user_manager, 'reset_user_password')
                reset_user_password('user-a', 'secure-password-456')
                self.assertIsNone(user_manager.validate_token(token))
                with self.assertRaises(ValueError):
                    user_manager.login('user-a', 'secure-password-123')
                new_token = user_manager.login('user-a', 'secure-password-456')
                self.assertEqual(user_manager.validate_token(new_token), 'user-a')

                listed = [item for item in user_manager.list_users() if item['user_id'] == 'user-a'][0]
                self.assertEqual(set(listed), {'user_id', 'role', 'created_at', 'has_password'})
                self.assertTrue(listed['has_password'])
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_user_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
                paths.RUNTIME_DATA_ROOT = original_paths_root

    def test_delete_user_archives_runtime_data_and_blocks_recreate_until_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_user_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            original_paths_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                paths.RUNTIME_DATA_ROOT = temp_root

                user_manager.create_user('user-a', 'secure-password-123')
                private_file = temp_root / 'user-a' / 'profile' / 'secret.txt'
                private_file.parent.mkdir(parents=True, exist_ok=True)
                private_file.write_text('private', encoding='utf-8')

                user_manager.delete_user('user-a')

                self.assertFalse((temp_root / 'user-a').exists())
                archived = list((temp_root / '_system' / 'deleted-users').glob('user-a-*'))
                self.assertEqual(len(archived), 1)
                self.assertTrue((archived[0] / 'profile' / 'secret.txt').exists())
                user_manager.create_user('user-a', 'secure-password-456')
                self.assertFalse((temp_root / 'user-a' / 'profile' / 'secret.txt').exists())
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_user_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
                paths.RUNTIME_DATA_ROOT = original_paths_root

    def test_concurrent_logins_preserve_all_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            original_hash_password = getattr(user_manager, '_hash_password')
            original_verify_password = getattr(user_manager, '_verify_password')
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                setattr(user_manager, '_hash_password', lambda password: f'hash:{password}')
                setattr(user_manager, '_verify_password', lambda password, hashed: hashed == f'hash:{password}')
                user_manager.set_admin_password('secure-password-123')

                tokens: list[str] = []
                errors: list[Exception] = []

                def worker() -> None:
                    try:
                        tokens.append(user_manager.login(paths.DEFAULT_USER_ID, 'secure-password-123'))
                    except Exception as err:
                        errors.append(err)

                threads = [threading.Thread(target=worker) for _ in range(20)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                self.assertEqual(errors, [])
                self.assertEqual(len(tokens), 20)
                sessions = json.loads(user_manager.SESSIONS_FILE.read_text(encoding='utf-8'))
                self.assertEqual(len(sessions), 20)
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
                setattr(user_manager, '_hash_password', original_hash_password)
                setattr(user_manager, '_verify_password', original_verify_password)

    def test_password_policy_rejects_whitespace_only_passwords(self):
        validate_password = getattr(user_manager, '_validate_password')
        with self.assertRaises(ValueError):
            validate_password('            ')

    def test_protected_routes_require_token_when_multi_user_enabled(self):
        original_is_multi_user_enabled = server.is_multi_user_enabled
        original_resolve_user_from_request = server.resolve_user_from_request
        try:
            server.is_multi_user_enabled = lambda: True
            server.resolve_user_from_request = lambda headers, **kwargs: None

            _, token, ok = server.begin_request_user_context('/api/state', 'GET', {})
            self.assertFalse(ok)
            self.assertIsNone(token)

            server.resolve_user_from_request = lambda headers, **kwargs: paths.DEFAULT_USER_ID
            uid, token, ok = server.begin_request_user_context('/api/state', 'GET', {'Authorization': 'Bearer token'})
            self.assertTrue(ok)
            self.assertEqual(uid, paths.DEFAULT_USER_ID)
            self.assertEqual(paths.active_user_id(), paths.DEFAULT_USER_ID)
            if token is not None:
                paths.reset_active_user_id(token)
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled
            server.resolve_user_from_request = original_resolve_user_from_request

    def test_user_asset_helpers_reject_path_ids_and_disable_shared_cache(self):
        is_valid_character_id_param = getattr(server, 'is_valid_character_id_param')
        user_asset_cache_headers = getattr(server, 'USER_ASSET_CACHE_HEADERS')
        self.assertTrue(is_valid_character_id_param('character-01'))
        self.assertTrue(is_valid_character_id_param('碎影江湖'))
        for value in ('../secret', 'a/b', 'has space', '', '..'):
            with self.subTest(value=value):
                self.assertFalse(is_valid_character_id_param(value))
        self.assertEqual(user_asset_cache_headers['Cache-Control'], 'no-store')

    def test_user_management_payload_strings_reject_non_strings(self):
        payload_string = getattr(server, 'payload_string')
        self.assertEqual(payload_string({'user_id': ' user-a '}, 'user_id'), 'user-a')
        self.assertEqual(payload_string({'password': '  keep spaces  '}, 'password'), '  keep spaces  ')
        for payload, key in (({'user_id': 123}, 'user_id'), ({'password': 123}, 'password'), ({}, 'user_id')):
            with self.subTest(payload=payload, key=key):
                with self.assertRaises(ValueError):
                    payload_string(payload, key)

    def test_toggle_payload_requires_boolean(self):
        payload_bool = getattr(server, 'payload_bool')
        self.assertTrue(payload_bool({'enabled': True}, 'enabled'))
        self.assertFalse(payload_bool({'enabled': False}, 'enabled'))
        for payload in ({'enabled': 'false'}, {'enabled': 1}, {}, {'enabled': None}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    payload_bool(payload, 'enabled')

    def test_decode_base64_limited_rejects_invalid_and_oversized_payloads(self):
        decode_base64_limited = getattr(server, 'decode_base64_limited')
        payload = base64.b64encode(b'abcd').decode('ascii')
        self.assertEqual(decode_base64_limited(payload, max_bytes=4, label='test'), b'abcd')
        with self.assertRaises(ValueError):
            decode_base64_limited(payload, max_bytes=3, label='test')
        with self.assertRaises(ValueError):
            decode_base64_limited('not-valid-base64', max_bytes=10, label='test')

    def test_decode_chat_import_content_rejects_invalid_utf8(self):
        decode_chat_import_content = getattr(server, 'decode_chat_import_content')
        payload = base64.b64encode(b'\xff\xfe').decode('ascii')
        with self.assertRaises(UnicodeDecodeError):
            decode_chat_import_content(payload)

    def test_character_import_base64_rejects_oversized_decoded_payload(self):
        original_limit = getattr(character_manager, 'MAX_CHARACTER_IMPORT_BYTES')
        try:
            setattr(character_manager, 'MAX_CHARACTER_IMPORT_BYTES', 1)
            payload = base64.b64encode(b'ab').decode('ascii')
            with self.assertRaises(ValueError):
                character_manager.import_character_card_base64('card.png', payload)
        finally:
            setattr(character_manager, 'MAX_CHARACTER_IMPORT_BYTES', original_limit)

    def test_character_manager_active_character_file_uses_active_user_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                (temp_root / paths.DEFAULT_USER_ID / 'characters' / 'char-a').mkdir(parents=True)
                (temp_root / 'user-a' / 'characters' / 'char-a').mkdir(parents=True)
                with paths.active_user_context('user-a'):
                    character_manager.set_active_character('char-a')

                user_active = temp_root / 'user-a' / 'config' / 'active-character.json'
                default_active = temp_root / paths.DEFAULT_USER_ID / 'config' / 'active-character.json'
                self.assertTrue(user_active.exists())
                self.assertFalse(default_active.exists())
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_admin_auth_requires_password_backed_default_user_token(self):
        original_admin_has_password = getattr(server, 'admin_has_password')
        original_validate_token = getattr(server, 'validate_token')
        authenticated_admin_from_token = getattr(server, 'authenticated_admin_from_token')
        try:
            setattr(server, 'admin_has_password', lambda: False)
            setattr(server, 'validate_token', lambda token: paths.DEFAULT_USER_ID)
            self.assertIsNone(authenticated_admin_from_token('token'))

            setattr(server, 'admin_has_password', lambda: True)
            setattr(server, 'validate_token', lambda token: 'user-a')
            self.assertIsNone(authenticated_admin_from_token('token'))

            setattr(server, 'validate_token', lambda token: paths.DEFAULT_USER_ID)
            self.assertEqual(authenticated_admin_from_token('token'), paths.DEFAULT_USER_ID)
        finally:
            setattr(server, 'admin_has_password', original_admin_has_password)
            setattr(server, 'validate_token', original_validate_token)

    def test_only_initial_set_admin_password_is_bootstrap_admin_action(self):
        original_admin_has_password = getattr(server, 'admin_has_password')
        original_is_multi_user_enabled = getattr(server, 'is_multi_user_enabled')
        is_admin_password_bootstrap_action = getattr(server, 'is_admin_password_bootstrap_action')
        try:
            setattr(server, 'admin_has_password', lambda: False)
            setattr(server, 'is_multi_user_enabled', lambda: False)
            self.assertTrue(is_admin_password_bootstrap_action('set_admin_password'))
            self.assertFalse(is_admin_password_bootstrap_action('create'))

            setattr(server, 'admin_has_password', lambda: True)
            self.assertFalse(is_admin_password_bootstrap_action('set_admin_password'))

            setattr(server, 'admin_has_password', lambda: False)
            setattr(server, 'is_multi_user_enabled', lambda: True)
            self.assertFalse(is_admin_password_bootstrap_action('set_admin_password'))
        finally:
            setattr(server, 'admin_has_password', original_admin_has_password)
            setattr(server, 'is_multi_user_enabled', original_is_multi_user_enabled)

    def test_business_payloads_must_not_include_user_id(self):
        business_payload_has_user_id = getattr(server, 'business_payload_has_user_id')
        business_query_has_user_id = getattr(server, 'business_query_has_user_id')
        self.assertFalse(business_payload_has_user_id('/api/auth/login', {'user_id': 'default-user'}))
        self.assertFalse(business_payload_has_user_id('/api/users', {'user_id': 'user-a'}))
        self.assertFalse(business_payload_has_user_id('/api/message', {'session_id': 's1'}))
        self.assertTrue(business_payload_has_user_id('/api/message', {'session_id': 's1', 'user_id': 'user-a'}))
        self.assertTrue(business_payload_has_user_id('/api/site-config', {'user_id': 'user-a'}))
        self.assertFalse(business_query_has_user_id('/api/users', {'user_id': ['user-a']}))
        self.assertTrue(business_query_has_user_id('/api/history', {'session_id': ['s1'], 'user_id': ['user-a']}))
        self.assertTrue(business_query_has_user_id('/api/history', {'session_id': ['s1'], 'user_id': ['']}))

    def test_business_user_id_rejection_handler_resets_context(self):
        original_is_multi_user_enabled = server.is_multi_user_enabled
        original_resolve_user_from_request = server.resolve_user_from_request
        try:
            server.is_multi_user_enabled = lambda: False
            server.resolve_user_from_request = lambda headers, **kwargs: paths.DEFAULT_USER_ID
            handler = make_business_reject_handler({'session_id': 's1', 'user_id': 'user-a'})
            server.Handler.do_POST(handler)
            sent = handler.sent
            self.assertIsNotNone(sent)
            if sent is None:
                self.fail('handler did not send a response')
            self.assertEqual(sent[0], 400)
            self.assertEqual(paths.active_user_id(), paths.DEFAULT_USER_ID)
            self.assertFalse(paths.is_multi_user_request_context())
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled
            server.resolve_user_from_request = original_resolve_user_from_request

    def test_ordinary_users_cannot_use_env_api_key_references_when_multi_user_enabled(self):
        original_is_multi_user_enabled = getattr(model_config, 'is_multi_user_enabled')
        validate_api_key_input = getattr(model_config, '_validate_api_key_input')
        resolve_api_key = getattr(model_config, '_resolve_api_key')
        try:
            setattr(model_config, 'is_multi_user_enabled', lambda: True)
            with paths.active_user_context('user-a'):
                with self.assertRaises(ValueError):
                    validate_api_key_input('env:SECRET_KEY')
                self.assertEqual(resolve_api_key('env:SECRET_KEY'), '')
            with paths.active_user_context(paths.DEFAULT_USER_ID):
                self.assertEqual(validate_api_key_input('env:SECRET_KEY'), 'env:SECRET_KEY')
        finally:
            setattr(model_config, 'is_multi_user_enabled', original_is_multi_user_enabled)

    def test_site_store_normalization_preserves_multi_user_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            temp_site = temp_root / paths.DEFAULT_USER_ID / 'config' / 'site.json'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                temp_site.parent.mkdir(parents=True, exist_ok=True)
                temp_site.write_text(
                    json.dumps({
                        'multi_user_enabled': True,
                        'site': {
                            'baseUrl': '',
                            'apiKey': '',
                            'api': 'openai-completions',
                            'models': [{'id': 'm1', 'name': 'M1'}],
                        },
                    }),
                    encoding='utf-8',
                )

                model_config.load_site_store()
                saved = json.loads(temp_site.read_text(encoding='utf-8'))
                self.assertTrue(saved['multi_user_enabled'])
                self.assertIn('site', saved)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_site_store_seed_preserves_multi_user_flag_when_site_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            temp_site = temp_root / paths.DEFAULT_USER_ID / 'config' / 'site.json'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                temp_site.parent.mkdir(parents=True, exist_ok=True)
                temp_site.write_text(json.dumps({'multi_user_enabled': True}), encoding='utf-8')

                model_config.load_site_store()
                saved = json.loads(temp_site.read_text(encoding='utf-8'))
                self.assertTrue(saved['multi_user_enabled'])
                self.assertIn('site', saved)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_site_config_updates_use_active_user_path(self):
        # New global contract: only default-user (admin) may update_site_config.
        # The write always lands in default-user/config/site.json regardless of
        # who is calling; ordinary users hit a permission error.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_user_manager_root = user_manager.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                user_manager.RUNTIME_DATA_ROOT = temp_root
                default_site = temp_root / paths.DEFAULT_USER_ID / 'config' / 'site.json'
                user_site = temp_root / 'user-a' / 'config' / 'site.json'
                default_site.parent.mkdir(parents=True, exist_ok=True)
                default_site.write_text(json.dumps({'multi_user_enabled': True}), encoding='utf-8')
                self.assertTrue(user_manager.is_multi_user_enabled())

                # Ordinary users are rejected.
                with paths.active_user_context('user-a'):
                    with self.assertRaises(model_config.SiteConfigPermissionError):
                        model_config.update_site_config({
                            'baseUrl': 'https://example.com',
                            'api': 'openai-completions',
                            'replace_api_key': True,
                            'apiKey': 'direct-key',
                        })

                # Admin write lands in the global file, not under another user.
                with paths.active_user_context(paths.DEFAULT_USER_ID):
                    model_config.update_site_config({
                        'baseUrl': 'https://example.com',
                        'api': 'openai-completions',
                        'replace_api_key': True,
                        'apiKey': 'direct-key',
                    })
                self.assertFalse(user_site.exists())
                saved_default = json.loads(default_site.read_text(encoding='utf-8'))
                self.assertTrue(saved_default['multi_user_enabled'])
                self.assertEqual(saved_default['site']['baseUrl'], 'https://example.com')
                self.assertEqual(saved_default['site']['apiKey'], 'direct-key')
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                user_manager.RUNTIME_DATA_ROOT = original_user_manager_root

    def test_ordinary_user_seed_from_global_provider_does_not_copy_api_key_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_paths_root = paths.RUNTIME_DATA_ROOT
            original_user_manager_root = user_manager.RUNTIME_DATA_ROOT
            original_global_providers = model_config.GLOBAL_PROVIDERS_CONFIG
            original_global_example = model_config.GLOBAL_PROVIDERS_EXAMPLE
            temp_root = Path(temp_dir)
            runtime_root = temp_root / 'runtime-data'
            global_providers = temp_root / 'providers.json'
            try:
                paths.RUNTIME_DATA_ROOT = runtime_root
                user_manager.RUNTIME_DATA_ROOT = runtime_root
                model_config.GLOBAL_PROVIDERS_CONFIG = global_providers
                model_config.GLOBAL_PROVIDERS_EXAMPLE = temp_root / 'missing-providers.example.json'
                default_site = runtime_root / paths.DEFAULT_USER_ID / 'config' / 'site.json'
                default_site.parent.mkdir(parents=True, exist_ok=True)
                default_site.write_text(json.dumps({'multi_user_enabled': True}), encoding='utf-8')
                global_providers.write_text(
                    json.dumps({'site': {'baseUrl': 'https://example.com', 'apiKey': 'env:OPENAI_API_KEY', 'api': 'openai-completions', 'models': []}}),
                    encoding='utf-8',
                )

                with paths.active_user_context('user-a'):
                    store = model_config.load_site_store()

                # Ordinary users see the same admin-owned site config; the env-
                # reference apiKey is sanitized to empty for them. They never
                # write their own site.json under the new global contract.
                self.assertEqual(store['site']['apiKey'], '')
                user_site = runtime_root / 'user-a' / 'config' / 'site.json'
                self.assertFalse(user_site.exists())
            finally:
                paths.RUNTIME_DATA_ROOT = original_paths_root
                user_manager.RUNTIME_DATA_ROOT = original_user_manager_root
                model_config.GLOBAL_PROVIDERS_CONFIG = original_global_providers
                model_config.GLOBAL_PROVIDERS_EXAMPLE = original_global_example

    def test_ensure_user_root_does_not_copy_default_user_character_for_new_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_template_root = paths.TEMPLATE_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                paths.TEMPLATE_ROOT = temp_root / '_template'
                default_private = temp_root / paths.DEFAULT_USER_ID / 'characters' / paths.DEFAULT_CHARACTER_ID / 'source'
                default_private.mkdir(parents=True, exist_ok=True)
                (default_private / 'character-data.json').write_text(json.dumps({'name': 'private'}), encoding='utf-8')

                paths.ensure_user_root('user-a')

                copied = temp_root / 'user-a' / 'characters' / paths.DEFAULT_CHARACTER_ID
                self.assertFalse(copied.exists())
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.TEMPLATE_ROOT = original_template_root

    def test_multi_user_layered_source_does_not_fallback_to_shared_private_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_profile = paths.SHARED_ROOT / 'player-profile.json'
                shared_profile.parent.mkdir(parents=True, exist_ok=True)
                shared_profile.write_text(json.dumps({'name': 'shared-private'}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        resolved = paths.resolve_layered_source('player-profile.json')
                    self.assertNotEqual(resolved, shared_profile)
                    self.assertEqual(resolved, paths.user_profile_root('user-a') / 'player-profile.json')
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_multi_user_player_profile_does_not_fallback_to_shared_legacy_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_profile = paths.SHARED_ROOT / 'player-profile.json'
                shared_profile.parent.mkdir(parents=True, exist_ok=True)
                shared_profile.write_text(json.dumps({'name': 'shared-private'}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertEqual(player_profile.load_base_player_profile(), {})
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_multi_user_player_profile_does_not_fallback_to_shared_base_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_profile = paths.SHARED_ROOT / 'player-profile.base.json'
                shared_profile.parent.mkdir(parents=True, exist_ok=True)
                shared_profile.write_text(json.dumps({'name': 'shared-private-base'}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertEqual(player_profile.load_base_player_profile(), {})
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_user_profile_route_uses_multi_user_context_before_loading_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            original_is_multi_user_enabled = server.is_multi_user_enabled
            original_resolve_user_from_request = server.resolve_user_from_request
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_profile = paths.SHARED_ROOT / 'player-profile.json'
                shared_profile.parent.mkdir(parents=True, exist_ok=True)
                shared_profile.write_text(json.dumps({'name': 'shared-private'}), encoding='utf-8')
                server.is_multi_user_enabled = lambda: True
                server.resolve_user_from_request = lambda headers, **kwargs: 'user-a'

                handler = make_get_handler('/api/user-profile')
                server.Handler.do_GET(handler)
                sent = handler.sent
                self.assertIsNotNone(sent)
                if sent is None:
                    self.fail('handler did not send a response')
                self.assertEqual(sent[0], 200)
                self.assertEqual(sent[1]['profile'], {})
                self.assertEqual(paths.active_user_id(), paths.DEFAULT_USER_ID)
                self.assertFalse(paths.is_multi_user_request_context())
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root
                server.is_multi_user_enabled = original_is_multi_user_enabled
                server.resolve_user_from_request = original_resolve_user_from_request

    def test_multi_user_runtime_store_does_not_fallback_to_shared_character_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_character = paths.SHARED_ROOT / 'character' / 'character-data.json'
                shared_character.parent.mkdir(parents=True, exist_ok=True)
                shared_character.write_text(json.dumps({'name': 'shared-private-character'}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        resolved = runtime_store.character_data_path()
                    self.assertNotEqual(resolved, shared_character)
                    self.assertEqual(resolved, paths.character_source_root(user_id='user-a') / 'character-data.json')
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_multi_user_active_character_id_does_not_derive_from_shared_character_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_character = paths.SHARED_ROOT / 'character' / 'character-data.json'
                shared_character.parent.mkdir(parents=True, exist_ok=True)
                shared_character.write_text(json.dumps({'name': 'shared-private-character'}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertEqual(paths.active_character_id(), paths.DEFAULT_CHARACTER_ID)
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_multi_user_active_character_id_uses_default_when_config_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                active_file = temp_root / 'user-a' / 'config' / paths.ACTIVE_CHARACTER_CONFIG_NAME
                active_file.parent.mkdir(parents=True, exist_ok=True)
                active_file.write_text(json.dumps({}), encoding='utf-8')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertEqual(paths.active_character_id(), paths.DEFAULT_CHARACTER_ID)
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_multi_user_character_cover_does_not_fallback_to_legacy_frontend_cover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_app_root = getattr(character_assets, 'APP_ROOT')
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                setattr(character_assets, 'APP_ROOT', temp_root / 'app')
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                cover = getattr(character_assets, 'APP_ROOT') / 'frontend' / 'character-cover-small.png'
                cover.parent.mkdir(parents=True, exist_ok=True)
                cover.write_bytes(b'private-cover')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertIsNone(character_assets.resolve_character_cover_path())
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                setattr(character_assets, 'APP_ROOT', original_app_root)
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_multi_user_character_cover_does_not_fallback_to_shared_imported_cover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                source_root = paths.character_source_root(character_id=paths.DEFAULT_CHARACTER_ID, user_id='user-a')
                source_root.mkdir(parents=True, exist_ok=True)
                (source_root / 'character-data.json').write_text(
                    json.dumps({'source': {'raw_card': 'abc12345.raw-card.json'}}),
                    encoding='utf-8',
                )
                shared_cover = paths.SHARED_ROOT / '角色卡' / 'abc12345.png'
                shared_cover.parent.mkdir(parents=True, exist_ok=True)
                shared_cover.write_bytes(b'private-cover')
                token = paths.set_multi_user_request_context(True)
                try:
                    with paths.active_user_context('user-a'):
                        self.assertIsNone(character_assets.resolve_character_cover_path())
                finally:
                    paths.reset_multi_user_request_context(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_multi_user_request_context_disables_legacy_session_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_app_root = paths.APP_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.APP_ROOT = temp_root / 'app'
                legacy_session = paths.APP_ROOT / 'sessions' / 'shared-session'
                legacy_session.mkdir(parents=True)

                paths.set_active_character_override('character-01')
                with paths.active_user_context('user-a'):
                    self.assertEqual(paths.resolve_session_dir('shared-session'), legacy_session)
                    token = paths.set_multi_user_request_context(True)
                    try:
                        resolved = paths.resolve_session_dir('shared-session')
                        self.assertNotEqual(resolved, legacy_session)
                        self.assertEqual(paths.session_roots(), [paths.current_sessions_root()])
                    finally:
                        paths.reset_multi_user_request_context(token)
            finally:
                paths.clear_active_character_override()
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.APP_ROOT = original_app_root

    def test_active_character_override_is_request_local(self):
        self.assertNotEqual(paths.active_character_id(), 'character-a')
        token_a = paths.set_active_character_override('character-a')
        try:
            self.assertEqual(paths.active_character_id(), 'character-a')
            token_b = paths.set_active_character_override('character-b')
            try:
                self.assertEqual(paths.active_character_id(), 'character-b')
            finally:
                paths.reset_active_character_override(token_b)
            self.assertEqual(paths.active_character_id(), 'character-a')
        finally:
            paths.reset_active_character_override(token_a)

    def test_history_cache_is_scoped_by_resolved_history_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            fixed_time = 1_700_000_000
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                for character_id, content in (('char-a', 'from-a'), ('char-b', 'from-b')):
                    history_path = temp_root / paths.DEFAULT_USER_ID / 'characters' / character_id / 'sessions' / 'same-session' / 'memory' / 'history.jsonl'
                    history_path.parent.mkdir(parents=True, exist_ok=True)
                    history_path.write_text(json.dumps({'role': 'user', 'content': content}) + '\n', encoding='utf-8')
                    os.utime(history_path, (fixed_time, fixed_time))

                token_a = paths.set_active_character_override('char-a')
                try:
                    first = runtime_store.load_history('same-session')
                finally:
                    paths.reset_active_character_override(token_a)

                token_b = paths.set_active_character_override('char-b')
                try:
                    second = runtime_store.load_history('same-session')
                finally:
                    paths.reset_active_character_override(token_b)

                self.assertEqual(first[0]['content'], 'from-a')
                self.assertEqual(second[0]['content'], 'from-b')
            finally:
                runtime_store.invalidate_history_cache()
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_shared_persona_seed_does_not_fallback_into_character_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_seed = paths.SHARED_ROOT / 'runtime' / 'persona-seeds' / 'scene' / 'Shared.json'
                shared_seed.parent.mkdir(parents=True, exist_ok=True)
                shared_seed.write_text(json.dumps({'display_name': 'Shared'}), encoding='utf-8')
                token = paths.set_active_character_override('char-a')
                try:
                    self.assertEqual(runtime_store.load_persona_index(), {})
                finally:
                    paths.reset_active_character_override(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root

    def test_stale_session_id_under_other_character_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                paths.RUNTIME_DATA_ROOT = temp_root
                other_session = temp_root / paths.DEFAULT_USER_ID / 'characters' / 'char-a' / 'sessions' / 'stale-session'
                other_session.mkdir(parents=True)
                token = paths.set_active_character_override('char-b')
                try:
                    handler = make_get_handler('/api/state?session_id=stale-session')
                    self.assertFalse(handler._validate_active_session_scope('stale-session', allow_missing=True))
                    self.assertIsNotNone(handler.sent)
                    if handler.sent is None:
                        self.fail('handler did not send a response')
                    status, payload = handler.sent
                    error = payload.get('error')
                    self.assertIsInstance(error, dict)
                    if not isinstance(error, dict):
                        self.fail('handler response did not include an error object')
                    self.assertEqual(status, 409)
                    self.assertEqual(error.get('code'), 'SESSION_CHARACTER_MISMATCH')
                finally:
                    paths.reset_active_character_override(token)
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_login_locks_account_after_failure_threshold(self):
        # H2: per-user lockout after N consecutive failed logins, releasing only
        # after the cooldown elapses or an admin resets the password.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            original_paths_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                paths.RUNTIME_DATA_ROOT = temp_root

                user_manager.create_user('user-a', 'secure-password-123')
                for _ in range(user_manager.LOGIN_FAILURE_LIMIT):
                    with self.assertRaises(ValueError):
                        user_manager.login('user-a', 'wrong-password-xxx')
                # Account is now locked even with correct password.
                with self.assertRaises(ValueError) as ctx:
                    user_manager.login('user-a', 'secure-password-123')
                self.assertIn('锁定', str(ctx.exception))

                # Admin password reset clears the lockout.
                user_manager.reset_user_password('user-a', 'secure-password-456')
                token = user_manager.login('user-a', 'secure-password-456')
                self.assertEqual(user_manager.validate_token(token), 'user-a')
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
                paths.RUNTIME_DATA_ROOT = original_paths_root

    def test_login_unknown_user_runs_dummy_bcrypt_to_hide_existence(self):
        # H3: ``user_not_found`` and ``wrong_password`` paths must both verify
        # against a bcrypt hash so response time cannot be used as a username
        # oracle.
        called_with: list[str] = []

        def fake_verify(password: str, hashed: str) -> bool:
            called_with.append(hashed)
            return False

        original_verify = getattr(user_manager, '_verify_password')
        original_users_file = user_manager.USERS_FILE
        original_sessions_file = user_manager.SESSIONS_FILE
        original_root = user_manager.RUNTIME_DATA_ROOT
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                setattr(user_manager, '_verify_password', fake_verify)

                with self.assertRaises(ValueError):
                    user_manager.login('non-existent-user', 'whatever-password')
            finally:
                setattr(user_manager, '_verify_password', original_verify)
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
        self.assertEqual(called_with, [user_manager._DUMMY_PASSWORD_HASH])

    def test_save_sessions_prunes_expired_entries(self):
        # M3: _save_sessions filters out expired entries so abandoned tokens
        # don't accumulate in sessions.json.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_sessions_file = user_manager.SESSIONS_FILE
            original_root = user_manager.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                user_manager._ensure_system_dir()

                now = time.time() if False else __import__('time').time()
                fresh_key = 'fresh-token-hash'
                stale_key = 'stale-token-hash'
                payload = {
                    fresh_key: {'user_id': 'user-a', 'created_at': now, 'last_seen_at': now, 'expires_at': now + 3600},
                    stale_key: {'user_id': 'user-b', 'created_at': now - 99999, 'last_seen_at': now - 99999, 'expires_at': now - 1},
                }
                user_manager._save_sessions(payload)
                saved = json.loads(user_manager.SESSIONS_FILE.read_text(encoding='utf-8'))
                self.assertIn(fresh_key, saved)
                self.assertNotIn(stale_key, saved)
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_enabling_multi_user_wipes_existing_sessions(self):
        # M5: switching multi-user ON must close the bootstrap window where a
        # default-user empty-password token could carry into multi-user state.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'

                user_manager.set_admin_password('secure-password-123')
                token = user_manager.login(paths.DEFAULT_USER_ID, 'secure-password-123')
                self.assertEqual(user_manager.validate_token(token), paths.DEFAULT_USER_ID)

                user_manager.set_multi_user_enabled(True)
                self.assertIsNone(user_manager.validate_token(token))
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_multi_user_toggle_requires_admin_password_server_side(self):
        original_is_multi_user_enabled = server.is_multi_user_enabled
        original_admin_has_password = server.admin_has_password
        original_validate_token = server.validate_token
        original_login = server.login
        original_set_multi_user_enabled = server.set_multi_user_enabled
        try:
            server.is_multi_user_enabled = lambda: True
            server.admin_has_password = lambda: True
            server.validate_token = lambda token: paths.DEFAULT_USER_ID
            toggles: list[bool] = []

            def fake_login(user_id: str, password: str) -> str:
                if user_id == paths.DEFAULT_USER_ID and password == 'correct-password-123':
                    return 'new-token'
                raise ValueError('bad credentials')

            server.login = fake_login
            server.set_multi_user_enabled = lambda enabled: toggles.append(enabled)

            missing = make_post_handler('/api/multi-user', {'enabled': False})
            server.Handler.do_POST(missing)
            self.assertEqual(missing.sent[0], 400)
            self.assertEqual(toggles, [])

            wrong = make_post_handler('/api/multi-user', {'enabled': False, 'password': 'wrong-password-123'})
            server.Handler.do_POST(wrong)
            self.assertEqual(wrong.sent[0], 401)
            self.assertEqual(toggles, [])

            ok = make_post_handler('/api/multi-user', {'enabled': False, 'password': 'correct-password-123'})
            server.Handler.do_POST(ok)
            self.assertEqual(ok.sent[0], 200)
            self.assertEqual(toggles, [False])
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled
            server.admin_has_password = original_admin_has_password
            server.validate_token = original_validate_token
            server.login = original_login
            server.set_multi_user_enabled = original_set_multi_user_enabled

    def test_post_request_rejects_cookie_session_token(self):
        # M1: cookie auth must not satisfy a POST/DELETE so a browser-issued
        # cross-site request cannot ride a session_token cookie.
        original_is_multi_user_enabled = server.is_multi_user_enabled
        try:
            server.is_multi_user_enabled = lambda: True
            captured: dict = {}

            def fake_resolve(headers, *, allow_cookie=True):
                captured['allow_cookie'] = allow_cookie
                return None

            original_resolve = server.resolve_user_from_request
            server.resolve_user_from_request = fake_resolve
            try:
                server.begin_request_user_context('/api/message', 'POST', {'Cookie': 'session_token=abc'})
            finally:
                server.resolve_user_from_request = original_resolve
            self.assertFalse(captured['allow_cookie'])
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled

    def test_get_request_still_accepts_cookie_session_token(self):
        # M1 sanity: GET endpoints continue to honour the cookie path so SSE
        # / EventSource flows that cannot set custom headers still work.
        original_is_multi_user_enabled = server.is_multi_user_enabled
        try:
            server.is_multi_user_enabled = lambda: True
            captured: dict = {}

            def fake_resolve(headers, *, allow_cookie=True):
                captured['allow_cookie'] = allow_cookie
                return paths.DEFAULT_USER_ID

            original_resolve = server.resolve_user_from_request
            server.resolve_user_from_request = fake_resolve
            try:
                _, token, ok = server.begin_request_user_context('/api/state', 'GET', {'Cookie': 'session_token=abc'})
                self.assertTrue(ok)
                if token is not None:
                    paths.reset_active_user_id(token)
            finally:
                server.resolve_user_from_request = original_resolve
            self.assertTrue(captured['allow_cookie'])
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled

    def test_session_locks_release_when_no_caller_holds_them(self):
        # M2: SESSION_LOCKS is a WeakValueDictionary; once no caller holds the
        # lock, the entry is GC-eligible. Otherwise the dict would grow once
        # per session_id seen for the lifetime of the process.
        import gc as _gc
        handler = make_get_handler('/api/state')
        lock = handler._session_lock('session-weakref-test')
        with lock:
            pass
        del lock
        _gc.collect()
        # The exact key encoding depends on the resolver, so verify by total
        # active count: no entries should reference the test session.
        for key in list(server.SESSION_LOCKS.keys()):
            self.assertNotIn('session-weakref-test', key)

    def test_session_quota_enforced_for_ordinary_multi_user_user(self):
        # M4: ordinary users in multi-user mode are bounded; default-user is
        # exempt; single-user mode has no quota.
        original_max = session_lifecycle.MAX_SESSIONS_PER_CHARACTER_FOR_USER
        original_runtime_root = paths.RUNTIME_DATA_ROOT
        original_is_multi_user_enabled = session_lifecycle.is_multi_user_enabled
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                session_lifecycle.MAX_SESSIONS_PER_CHARACTER_FOR_USER = 2
                paths.RUNTIME_DATA_ROOT = temp_root
                session_lifecycle.is_multi_user_enabled = lambda: True
                sessions_root = paths.character_sessions_root(character_id='char-a', user_id='user-a')
                sessions_root.mkdir(parents=True)
                (sessions_root / 'session-1').mkdir()
                (sessions_root / 'session-2').mkdir()
                # archive- folders don't count
                (sessions_root / 'archive-stale').mkdir()

                token_user = paths.set_active_character_override('char-a')
                try:
                    with paths.active_user_context('user-a'):
                        with self.assertRaises(ValueError):
                            session_lifecycle._enforce_session_quota()
                    # default-user is exempt even when multi-user is on.
                    default_sessions = paths.character_sessions_root(character_id='char-a', user_id=paths.DEFAULT_USER_ID)
                    default_sessions.mkdir(parents=True)
                    (default_sessions / 'session-1').mkdir()
                    (default_sessions / 'session-2').mkdir()
                    (default_sessions / 'session-3').mkdir()
                    with paths.active_user_context(paths.DEFAULT_USER_ID):
                        session_lifecycle._enforce_session_quota()
                finally:
                    paths.reset_active_character_override(token_user)

                # single-user mode: no quota at all
                session_lifecycle.is_multi_user_enabled = lambda: False
                token_solo = paths.set_active_character_override('char-a')
                try:
                    with paths.active_user_context('user-a'):
                        session_lifecycle._enforce_session_quota()
                finally:
                    paths.reset_active_character_override(token_solo)
            finally:
                session_lifecycle.MAX_SESSIONS_PER_CHARACTER_FOR_USER = original_max
                session_lifecycle.is_multi_user_enabled = original_is_multi_user_enabled
                paths.RUNTIME_DATA_ROOT = original_runtime_root

    def test_change_own_password_keeps_current_token_revokes_others(self):
        # Q3: self-service change-password keeps the current Bearer alive but
        # revokes any other token belonging to the same user, so an old device
        # cannot continue acting under the previous credentials.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            original_paths_root = paths.RUNTIME_DATA_ROOT
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                paths.RUNTIME_DATA_ROOT = temp_root

                user_manager.create_user('user-a', 'secure-password-123')
                token_kept = user_manager.login('user-a', 'secure-password-123')
                token_other = user_manager.login('user-a', 'secure-password-123')
                self.assertEqual(user_manager.validate_token(token_kept), 'user-a')
                self.assertEqual(user_manager.validate_token(token_other), 'user-a')

                user_manager.change_own_password(
                    'user-a',
                    'secure-password-123',
                    'secure-password-456',
                    keep_token=token_kept,
                )

                self.assertEqual(user_manager.validate_token(token_kept), 'user-a')
                self.assertIsNone(user_manager.validate_token(token_other))
                with self.assertRaises(ValueError):
                    user_manager.login('user-a', 'secure-password-123')
                user_manager.login('user-a', 'secure-password-456')
            finally:
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file
                paths.RUNTIME_DATA_ROOT = original_paths_root

    def test_change_own_password_unknown_user_runs_dummy_bcrypt(self):
        called_with: list[str] = []
        original_verify = getattr(user_manager, '_verify_password')

        def fake_verify(password: str, hashed: str) -> bool:
            called_with.append(hashed)
            return original_verify(password, hashed)

        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = user_manager.RUNTIME_DATA_ROOT
            original_users_file = user_manager.USERS_FILE
            original_sessions_file = user_manager.SESSIONS_FILE
            temp_root = Path(temp_dir)
            try:
                user_manager.RUNTIME_DATA_ROOT = temp_root
                user_manager.USERS_FILE = temp_root / '_system' / 'users.json'
                user_manager.SESSIONS_FILE = temp_root / '_system' / 'sessions.json'
                setattr(user_manager, '_verify_password', fake_verify)
                with self.assertRaises(ValueError):
                    user_manager.change_own_password('ghost-user', 'whatever', 'secure-password-123')
                self.assertIn(user_manager._DUMMY_PASSWORD_HASH, called_with)
            finally:
                setattr(user_manager, '_verify_password', original_verify)
                user_manager.RUNTIME_DATA_ROOT = original_root
                user_manager.USERS_FILE = original_users_file
                user_manager.SESSIONS_FILE = original_sessions_file

    def test_auth_me_returns_role_for_admin_and_user(self):
        # B3: /api/auth/me must signal which role is logged in so the frontend
        # can branch the settings panel.
        original_is_multi_user_enabled = server.is_multi_user_enabled
        original_resolve = server.resolve_user_from_request
        original_admin_has_password = server.admin_has_password
        try:
            server.is_multi_user_enabled = lambda: True
            server.admin_has_password = lambda: True

            server.resolve_user_from_request = lambda headers, **kwargs: paths.DEFAULT_USER_ID
            handler = make_get_handler('/api/auth/me')
            server.Handler.do_GET(handler)
            sent = handler.sent
            self.assertIsNotNone(sent)
            assert sent is not None
            self.assertEqual(sent[0], 200)
            self.assertEqual(sent[1]['role'], 'admin')
            self.assertEqual(sent[1]['user_id'], paths.DEFAULT_USER_ID)
            self.assertTrue(sent[1]['multi_user_enabled'])
            self.assertTrue(sent[1]['admin_has_password'])

            server.resolve_user_from_request = lambda headers, **kwargs: 'user-a'
            handler = make_get_handler('/api/auth/me')
            server.Handler.do_GET(handler)
            sent = handler.sent
            assert sent is not None
            self.assertEqual(sent[0], 200)
            self.assertEqual(sent[1]['role'], 'user')
        finally:
            server.is_multi_user_enabled = original_is_multi_user_enabled
            server.resolve_user_from_request = original_resolve
            server.admin_has_password = original_admin_has_password

    def test_provider_and_site_config_write_rejected_for_ordinary_user(self):
        # B1/Q2: provider + site config follow the same admin-only contract.
        with paths.active_user_context('user-a'):
            with self.assertRaises(model_config.SiteConfigPermissionError):
                model_config.upsert_provider_config({
                    'baseUrl': 'https://example.com',
                    'api': 'openai-completions',
                    'replace_api_key': True,
                    'apiKey': '',
                })
            with self.assertRaises(model_config.SiteConfigPermissionError):
                model_config.discover_site_models()

    def test_character_card_quota_enforced_for_ordinary_multi_user_user(self):
        # M4: a non-default-user under multi-user mode cannot import beyond the
        # cap; default-user and single-user mode bypass.
        original_max = character_manager.MAX_CHARACTER_CARDS_FOR_USER
        original_runtime_root = paths.RUNTIME_DATA_ROOT
        original_is_multi_user_enabled = character_manager.is_multi_user_enabled
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir) / 'runtime-data'
            try:
                character_manager.MAX_CHARACTER_CARDS_FOR_USER = 2
                paths.RUNTIME_DATA_ROOT = temp_root
                character_manager.is_multi_user_enabled = lambda: True
                user_a_chars = temp_root / 'user-a' / 'characters'
                user_a_chars.mkdir(parents=True)
                (user_a_chars / 'char-1').mkdir()
                (user_a_chars / 'char-2').mkdir()

                with paths.active_user_context('user-a'):
                    with self.assertRaises(ValueError):
                        character_manager._enforce_character_quota()

                # default-user exempt
                default_chars = temp_root / paths.DEFAULT_USER_ID / 'characters'
                default_chars.mkdir(parents=True)
                for n in ('a', 'b', 'c', 'd'):
                    (default_chars / n).mkdir()
                with paths.active_user_context(paths.DEFAULT_USER_ID):
                    character_manager._enforce_character_quota()

                # single-user mode: no quota
                character_manager.is_multi_user_enabled = lambda: False
                with paths.active_user_context('user-a'):
                    character_manager._enforce_character_quota()
            finally:
                character_manager.MAX_CHARACTER_CARDS_FOR_USER = original_max
                character_manager.is_multi_user_enabled = original_is_multi_user_enabled
                paths.RUNTIME_DATA_ROOT = original_runtime_root


if __name__ == '__main__':
    unittest.main()
