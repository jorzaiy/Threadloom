#!/usr/bin/env python3
import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

handler_message = importlib.import_module('handler_message')
runtime_store = importlib.import_module('runtime_store')


def _model_config(model_id: str) -> dict[str, object]:
    return {
        'provider_name': 'site',
        'provider': {'baseUrl': 'https://example.test/v1', 'apiKey': ''},
        'model': {'id': model_id},
        'temperature': 0.8,
        'max_output_tokens': 100,
        'stream': False,
    }


def test_narrator_retries_incomplete_replies(monkeypatch):
    replies = [
        ('半截正文，', {'finish_reason': 'length', 'model': 'narrator'}),
        ('仍然没有句号', {'finish_reason': 'stop', 'model': 'narrator'}),
        ('完整正文。', {'finish_reason': 'stop', 'model': 'narrator'}),
    ]

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        return replies.pop(0)

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == '完整正文。'
    assert usage['finish_reason'] == 'stop'
    assert trace['all_failed'] is False
    assert len(trace['attempts']) == 3
    assert trace['attempts'][0]['ok'] is False
    assert trace['attempts'][1]['ok'] is False
    assert trace['attempts'][2]['ok'] is True


def test_narrator_returns_unavailable_after_three_incomplete_replies(monkeypatch):
    attempts = []

    def fake_resolve_provider_model(role):
        return _model_config(role)

    def fake_call_model(_model_cfg, _system_prompt, _user_prompt):
        attempts.append(1)
        return '像一头耐心的狼，领着一群疲惫的', {'finish_reason': 'stop', 'model': 'narrator'}

    monkeypatch.setattr(handler_message, 'resolve_provider_model', fake_resolve_provider_model)
    monkeypatch.setattr(handler_message, 'call_model', fake_call_model)

    reply, usage, trace = handler_message._call_narrator_with_retries('system', 'user')

    assert reply == ''
    assert usage['finish_reason'] == 'error'
    assert trace['all_failed'] is True
    assert trace['last_error'] == 'incomplete narrator reply'
    assert len(trace['attempts']) == 3
    assert len(attempts) == 3


def test_history_filter_hides_partial_turn_pair():
    history = [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '继续'},
        {'role': 'assistant', 'content': '半截正文', 'completion_status': 'partial'},
    ]

    assert runtime_store.filter_committed_history_items(history) == [
        {'role': 'assistant', 'content': '开场。'},
    ]


def test_append_history_discards_existing_partial_pair_before_new_user(monkeypatch):
    history = [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '继续'},
        {'role': 'assistant', 'content': '半截正文', 'completion_status': 'partial'},
    ]
    saved = {}

    monkeypatch.setattr(runtime_store, 'load_history', lambda _session_id: list(history))
    monkeypatch.setattr(runtime_store, 'save_history', lambda _session_id, items: saved.setdefault('items', items))

    runtime_store.append_history('session', {'role': 'user', 'content': '换个动作'})

    assert saved['items'] == [
        {'role': 'assistant', 'content': '开场。'},
        {'role': 'user', 'content': '换个动作'},
    ]
