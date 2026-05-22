#!/usr/bin/env python3
import sys
from pathlib import Path
from contextlib import nullcontext
from http.client import HTTPMessage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import server  # noqa: E402
from session_auditor import analyze_style_drift, run_session_audit  # noqa: E402


def test_style_drift_detects_repeated_micro_actions():
    history = []
    verbose = '年轻男人的嘴巴张了一下，喉结动了一下，手指攥紧又松开，背脊绷住。' * 30
    for idx in range(6):
        history.append({'role': 'user', 'content': f'继续{idx}'})
        history.append({'role': 'assistant', 'content': verbose, 'turn_id': f'turn-{idx:04d}'})

    result = analyze_style_drift(history, window_turns=6)

    assert result['status'] in {'warning', 'critical'}
    assert result['assistant_turns'] == 6
    assert result['avg_micro_action_score'] > 20


def test_manual_audit_is_report_only(monkeypatch):
    history = [
        {'role': 'user', 'content': '问药铺掌柜'},
        {'role': 'assistant', 'content': '年轻男人的嘴巴张了一下，喉结动了一下，手指攥紧又松开。' * 30, 'turn_id': 'turn-0083'},
    ]
    events = {
        'items': [
            {
                'event_id': 'evt_0082',
                'turn_id': 'turn-0082',
                'provider': 'heuristic',
                'summary': '嘴巴张了一下，喉结动了一下，手指攥紧又松开，背脊绷住。' * 5,
            }
        ]
    }
    state = {
        'actor_persona_hooks': {
            'npc_1': {
                'display_name': '年轻男人',
                'mannerisms': ['喉结动了一下', '手指攥紧又松开'],
            }
        }
    }
    saved = []
    monkeypatch.setattr('session_auditor.load_history', lambda _session_id: history)
    monkeypatch.setattr('session_auditor.load_event_summaries', lambda _session_id: events)
    monkeypatch.setattr('session_auditor.load_state', lambda _session_id: state)
    monkeypatch.setattr('session_auditor.save_audit_report', lambda session_id, report: saved.append((session_id, report)))

    report = run_session_audit('demo-session', save=True)

    assert report['mode'] == 'manual_mvp'
    assert report['severity'] in {'warning', 'critical'}
    assert report['summary']['polluted_event_summary_count'] == 1
    assert report['summary']['persona_hook_issue_count'] == 1
    assert report['safe_auto_repairs'] == []
    assert saved and saved[0][0] == 'demo-session'


def test_session_audit_endpoint_returns_report(monkeypatch):
    class CaptureHandler(server.Handler):
        payload = {}
        sent: tuple[int, dict] | None = None

        def _read_json_payload(self):
            return self.payload

        def _send(self, status, payload):
            self.sent = (status, payload)
            return True

        def _invalid_input(self, message):
            self.sent = (400, {'error': {'message': message}})
            return True

        def _validate_active_session_scope(self, session_id, allow_missing=False):
            return True

        def _session_exists(self, session_id):
            return True

        def _session_lock(self, session_id):
            return nullcontext()

    handler = object.__new__(CaptureHandler)
    handler.path = '/api/session-audit'
    handler.headers = HTTPMessage()
    handler.client_address = ('127.0.0.1', 12345)
    handler.payload = {'session_id': 'demo-session'}
    handler.sent = None
    monkeypatch.setattr(server, 'begin_request_user_context', lambda path, method, headers: ('default-user', None, True))
    monkeypatch.setattr(server, 'begin_multi_user_request_context', lambda: None)
    monkeypatch.setattr(server, 'reset_multi_user_request_context', lambda token: None)
    monkeypatch.setattr(server, 'run_session_audit', lambda session_id: {'session_id': session_id, 'severity': 'ok'})
    monkeypatch.setattr(server, 'web_runtime_settings', lambda: {'show_debug_panel': True})

    server.Handler.do_POST(handler)

    sent = getattr(handler, 'sent', None)
    assert sent is not None
    status, payload = sent
    assert status == 200
    assert payload['session_id'] == 'demo-session'
    assert payload['audit']['severity'] == 'ok'
