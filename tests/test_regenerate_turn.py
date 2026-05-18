#!/usr/bin/env python3
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

regenerate_turn = importlib.import_module('regenerate_turn')


def test_complete_regenerate_restores_artifacts_and_preserves_user(monkeypatch, tmp_path):
    session_id = 'regen-session'
    original_user = {'ts': 100, 'role': 'user', 'content': '原本的用户输入'}
    old_assistant = {'ts': 101, 'role': 'assistant', 'content': '不满意的输出', 'completion_status': 'complete'}
    history_store = {'items': [original_user, old_assistant]}
    meta_store = {
        'data': {
            'last_turn_id': 3,
            'processed_client_turn_ids': {
                'web-1': {'turn_id': 'turn-0003', 'reply': '不满意的输出'},
                'web-0': {'turn_id': 'turn-0002', 'reply': '旧输出'},
            },
            'turn_audits': [
                {'turn_id': 'turn-0002'},
                {'turn_id': 'turn-0003'},
            ],
            'last_turn_audit': {'turn_id': 'turn-0003'},
        }
    }
    saved_state = {}
    saved_persona = {}
    saved_events = {}
    saved_chunks = {}
    summary_updates = []
    keeper_archive = tmp_path / 'keeper_record_archive.json'
    keeper_archive.write_text('{}', encoding='utf-8')

    def fake_save_history(_session_id, items):
        history_store['items'] = list(items)

    def fake_handle_message(payload):
        assert payload['text'] == original_user['content']
        history_store['items'] = [
            {'ts': 200, 'role': 'user', 'content': original_user['content']},
            {'ts': 201, 'role': 'assistant', 'content': '新的输出', 'completion_status': 'complete'},
        ]
        meta_store['data']['last_turn_id'] = 3
        return {'session_id': payload['session_id'], 'turn_id': 'turn-0003', 'reply': '新的输出'}

    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: list(history_store['items']))
    monkeypatch.setattr(regenerate_turn, 'save_history', fake_save_history)
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: dict(meta_store['data']))
    monkeypatch.setattr(regenerate_turn, 'save_meta', lambda _session_id, meta: meta_store.update(data=meta))
    monkeypatch.setattr(regenerate_turn, 'load_turn_trace', lambda _session_id, _turn_id: {
        'pre_turn': {
            'state': {'main_event': '旧状态'},
            'persona_layers': {'scene': {}, 'archive': {}, 'longterm': {}},
        }
    })
    monkeypatch.setattr(regenerate_turn, 'save_state', lambda _session_id, state: saved_state.update(state=state))
    monkeypatch.setattr(regenerate_turn, 'save_session_persona_layers', lambda _session_id, layers: saved_persona.update(layers=layers))
    monkeypatch.setattr(regenerate_turn, 'load_event_summaries', lambda _session_id: {
        'version': 1,
        'items': [{'turn_id': 'turn-0002'}, {'turn_id': 'turn-0003'}],
    })
    monkeypatch.setattr(regenerate_turn, 'save_event_summaries', lambda _session_id, payload: saved_events.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'save_summary_chunks', lambda _session_id, payload: saved_chunks.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'update_summary', lambda _session_id: summary_updates.append(_session_id) or '# Summary\n')
    monkeypatch.setattr(regenerate_turn, 'session_paths', lambda _session_id: {'keeper_archive': keeper_archive})
    monkeypatch.setattr(regenerate_turn, 'handle_message', fake_handle_message)

    result = regenerate_turn.regenerate_last_partial(session_id, allow_complete=True)

    assert result['reply'] == '新的输出'
    assert history_store['items'][0] == original_user
    assert history_store['items'][1]['content'] == '新的输出'
    assert meta_store['data']['last_turn_id'] == 3
    assert 'web-1' not in meta_store['data']['processed_client_turn_ids']
    assert meta_store['data']['processed_client_turn_ids']['web-0']['turn_id'] == 'turn-0002'
    assert meta_store['data']['turn_audits'] == [{'turn_id': 'turn-0002'}]
    assert meta_store['data']['last_turn_audit'] == {'turn_id': 'turn-0002'}
    assert saved_state['state'] == {'main_event': '旧状态'}
    assert saved_persona['layers'] == {'scene': {}, 'archive': {}, 'longterm': {}}
    assert saved_events['payload']['items'] == [{'turn_id': 'turn-0002'}]
    assert saved_chunks['payload'] == {'version': 1, 'chunks': []}
    assert summary_updates == [session_id]
    assert not keeper_archive.exists()


def test_complete_regenerate_requires_turn_trace(monkeypatch):
    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: [
        {'role': 'user', 'content': '输入'},
        {'role': 'assistant', 'content': '输出', 'completion_status': 'complete'},
    ])
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: {'last_turn_id': 1, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(regenerate_turn, 'load_turn_trace', lambda _session_id, _turn_id: {})

    result = regenerate_turn.regenerate_last_partial('session', allow_complete=True)

    assert result['error']['code'] == 'TURN_TRACE_MISSING'


def test_complete_regenerate_restores_snapshot_when_generation_fails(monkeypatch, tmp_path):
    session_id = 'regen-fails'
    original_history = [
        {'ts': 100, 'role': 'user', 'content': '原本的用户输入'},
        {'ts': 101, 'role': 'assistant', 'content': '旧输出', 'completion_status': 'complete'},
    ]
    original_meta = {'last_turn_id': 4, 'processed_client_turn_ids': {'web-1': {'turn_id': 'turn-0004'}}}
    history_store = {'items': list(original_history)}
    meta_store = {'data': dict(original_meta)}
    state_store = {'state': {'main_event': '旧提交状态'}}
    persona_store = {'layers': {'scene': {'甲': {'display_name': '甲'}}, 'archive': {}, 'longterm': {}}}
    events_store = {'payload': {'version': 1, 'items': [{'turn_id': 'turn-0004'}]}}
    chunks_store = {'payload': {'version': 1, 'chunks': [{'chunk_id': 'chunk_0001'}]}}
    summary_store = {'text': '# Old Summary\n'}
    keeper_archive = tmp_path / 'keeper_record_archive.json'
    keeper_archive.write_text('{"records":[1]}', encoding='utf-8')

    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: list(history_store['items']))
    monkeypatch.setattr(regenerate_turn, 'save_history', lambda _session_id, items: history_store.update(items=list(items)))
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: dict(meta_store['data']))
    monkeypatch.setattr(regenerate_turn, 'save_meta', lambda _session_id, meta: meta_store.update(data=dict(meta)))
    monkeypatch.setattr(regenerate_turn, 'load_state', lambda _session_id: dict(state_store['state']))
    monkeypatch.setattr(regenerate_turn, 'save_state', lambda _session_id, state: state_store.update(state=dict(state)))
    monkeypatch.setattr(regenerate_turn, 'load_session_persona_layers', lambda _session_id: dict(persona_store['layers']))
    monkeypatch.setattr(regenerate_turn, 'save_session_persona_layers', lambda _session_id, layers: persona_store.update(layers=layers))
    monkeypatch.setattr(regenerate_turn, 'load_event_summaries', lambda _session_id: dict(events_store['payload']))
    monkeypatch.setattr(regenerate_turn, 'save_event_summaries', lambda _session_id, payload: events_store.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'load_summary_chunks', lambda _session_id: dict(chunks_store['payload']))
    monkeypatch.setattr(regenerate_turn, 'save_summary_chunks', lambda _session_id, payload: chunks_store.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'load_summary', lambda _session_id: summary_store['text'])
    monkeypatch.setattr(regenerate_turn, 'save_summary', lambda _session_id, text: summary_store.update(text=text))
    monkeypatch.setattr(regenerate_turn, 'update_summary', lambda _session_id: summary_store.update(text='# Rolled Back\n') or '# Rolled Back\n')
    monkeypatch.setattr(regenerate_turn, 'session_paths', lambda _session_id: {'keeper_archive': keeper_archive})
    monkeypatch.setattr(regenerate_turn, 'load_turn_trace', lambda _session_id, _turn_id: {
        'pre_turn': {
            'state': {'main_event': 'pre-turn'},
            'persona_layers': {'scene': {}, 'archive': {}, 'longterm': {}},
        }
    })
    monkeypatch.setattr(regenerate_turn, 'handle_message', lambda _payload: {'error': {'code': 'NARRATOR_UNAVAILABLE'}})

    result = regenerate_turn.regenerate_last_partial(session_id, allow_complete=True)

    assert result['error']['code'] == 'NARRATOR_UNAVAILABLE'
    assert history_store['items'] == original_history
    assert meta_store['data'] == original_meta
    assert state_store['state'] == {'main_event': '旧提交状态'}
    assert persona_store['layers'] == {'scene': {'甲': {'display_name': '甲'}}, 'archive': {}, 'longterm': {}}
    assert events_store['payload'] == {'version': 1, 'items': [{'turn_id': 'turn-0004'}]}
    assert chunks_store['payload'] == {'version': 1, 'chunks': [{'chunk_id': 'chunk_0001'}]}
    assert summary_store['text'] == '# Old Summary\n'
    assert keeper_archive.read_text(encoding='utf-8') == '{"records":[1]}'


def test_partial_regenerate_keeps_existing_behavior(monkeypatch):
    history_store = {'items': [
        {'role': 'user', 'content': '输入'},
        {'ts': 9, 'role': 'assistant', 'content': '半截', 'completion_status': 'partial'},
    ]}
    meta_store = {'data': {'last_turn_id': 1, 'processed_client_turn_ids': {'web-1': {'turn_id': 'turn-0001'}}}}

    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: list(history_store['items']))
    monkeypatch.setattr(regenerate_turn, 'save_history', lambda _session_id, items: history_store.update(items=list(items)))
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: dict(meta_store['data']))
    monkeypatch.setattr(regenerate_turn, 'save_meta', lambda _session_id, meta: meta_store.update(data=meta))
    monkeypatch.setattr(regenerate_turn, 'handle_message', lambda payload: {'reply': f"新：{payload['text']}", 'turn_id': 'turn-0001'})

    result = regenerate_turn.regenerate_last_partial('session')

    assert result['reply'] == '新：输入'
    assert history_store['items'] == []
    assert meta_store['data']['last_turn_id'] == 0
    assert meta_store['data']['processed_client_turn_ids'] == {}


def test_delete_latest_turn_restores_pre_turn_artifacts(monkeypatch, tmp_path):
    session_id = 'delete-turn-session'
    history_store = {'items': [
        {'ts': 90, 'role': 'user', 'content': '旧输入'},
        {'ts': 91, 'role': 'assistant', 'content': '旧回复', 'completion_status': 'complete'},
        {'ts': 100, 'role': 'user', 'content': '误触输入'},
        {'ts': 101, 'role': 'assistant', 'content': '误触回复', 'completion_status': 'complete'},
    ]}
    meta_store = {'data': {
        'last_turn_id': 5,
        'processed_client_turn_ids': {
            'web-5': {'turn_id': 'turn-0005', 'reply': '误触回复'},
            'web-4': {'turn_id': 'turn-0004', 'reply': '旧回复'},
        },
        'turn_audits': [{'turn_id': 'turn-0004'}, {'turn_id': 'turn-0005'}],
        'last_turn_audit': {'turn_id': 'turn-0005'},
    }}
    saved_state = {}
    saved_persona = {}
    saved_events = {}
    saved_chunks = {}
    summary_updates = []
    keeper_archive = tmp_path / 'keeper_record_archive.json'
    keeper_archive.write_text(json.dumps({
        'version': 1,
        'source_pair_count': 5,
        'history_message_count': 4,
        'records': [
            {'provider': 'heuristic', 'window': {'end_pair_index': 4}, 'history_digest': ['旧记录']},
            {'provider': 'manual-cleanup', 'window': {'end_pair_index': 4}, 'history_digest': ['人工清理记录']},
            {'provider': 'heuristic', 'window': {'end_pair_index': 5}, 'history_digest': ['误触记录']},
        ],
    }, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: list(history_store['items']))
    monkeypatch.setattr(regenerate_turn, 'save_history', lambda _session_id, items: history_store.update(items=list(items)))
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: dict(meta_store['data']))
    monkeypatch.setattr(regenerate_turn, 'save_meta', lambda _session_id, meta: meta_store.update(data=meta))
    monkeypatch.setattr(regenerate_turn, 'load_state', lambda _session_id: {'main_event': '误触后状态'})
    monkeypatch.setattr(regenerate_turn, 'load_session_persona_layers', lambda _session_id: {'scene': {'误触人物': {}}, 'archive': {}, 'longterm': {}})
    monkeypatch.setattr(regenerate_turn, 'load_event_summaries', lambda _session_id: {'version': 1, 'items': [{'turn_id': 'turn-0004'}, {'turn_id': 'turn-0005'}]})
    monkeypatch.setattr(regenerate_turn, 'load_summary_chunks', lambda _session_id: {
        'version': 1,
        'chunks': [
            {'chunk_id': 'chunk_0001', 'turn_end': 4},
            {'chunk_id': 'chunk_0002', 'turn_end': 5},
        ],
    })
    monkeypatch.setattr(regenerate_turn, 'load_summary', lambda _session_id: '# Before delete snapshot\n')
    monkeypatch.setattr(regenerate_turn, 'load_turn_trace', lambda _session_id, _turn_id: {
        'pre_turn': {
            'state': {'main_event': '误触前状态'},
            'persona_layers': {'scene': {}, 'archive': {}, 'longterm': {}},
        }
    })
    monkeypatch.setattr(regenerate_turn, 'save_state', lambda _session_id, state: saved_state.update(state=state))
    monkeypatch.setattr(regenerate_turn, 'save_session_persona_layers', lambda _session_id, layers: saved_persona.update(layers=layers))
    monkeypatch.setattr(regenerate_turn, 'save_event_summaries', lambda _session_id, payload: saved_events.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'save_summary_chunks', lambda _session_id, payload: saved_chunks.update(payload=payload))
    monkeypatch.setattr(regenerate_turn, 'update_summary', lambda _session_id: summary_updates.append(_session_id) or '# Rolled Back\n')
    monkeypatch.setattr(regenerate_turn, 'session_paths', lambda _session_id: {'keeper_archive': keeper_archive})

    result = regenerate_turn.delete_latest_turn(session_id)

    assert result['ok'] is True
    assert result['deleted_turn_id'] == 'turn-0005'
    assert result['deleted_user_text'] == '误触输入'
    assert history_store['items'] == [
        {'ts': 90, 'role': 'user', 'content': '旧输入'},
        {'ts': 91, 'role': 'assistant', 'content': '旧回复', 'completion_status': 'complete'},
    ]
    assert meta_store['data']['last_turn_id'] == 4
    assert 'web-5' not in meta_store['data']['processed_client_turn_ids']
    assert meta_store['data']['processed_client_turn_ids']['web-4']['turn_id'] == 'turn-0004'
    assert meta_store['data']['turn_audits'] == [{'turn_id': 'turn-0004'}]
    assert meta_store['data']['last_turn_audit'] == {'turn_id': 'turn-0004'}
    assert saved_state['state'] == {'main_event': '误触前状态'}
    assert saved_persona['layers'] == {'scene': {}, 'archive': {}, 'longterm': {}}
    assert saved_events['payload']['items'] == [{'turn_id': 'turn-0004'}]
    assert saved_chunks['payload'] == {'version': 1, 'chunks': [{'chunk_id': 'chunk_0001', 'turn_end': 4}]}
    assert summary_updates == [session_id]
    archive = json.loads(keeper_archive.read_text(encoding='utf-8'))
    assert archive['source_pair_count'] == 4
    assert archive['history_message_count'] == 2
    assert archive['records'] == [
        {'provider': 'heuristic', 'window': {'end_pair_index': 4}, 'history_digest': ['旧记录']},
        {'provider': 'manual-cleanup', 'window': {'end_pair_index': 4}, 'history_digest': ['人工清理记录']},
    ]


def test_delete_latest_turn_requires_trace_for_complete_turn(monkeypatch):
    monkeypatch.setattr(regenerate_turn, 'load_history', lambda _session_id: [
        {'role': 'user', 'content': '输入'},
        {'role': 'assistant', 'content': '输出', 'completion_status': 'complete'},
    ])
    monkeypatch.setattr(regenerate_turn, 'load_meta', lambda _session_id: {'last_turn_id': 1})
    monkeypatch.setattr(regenerate_turn, 'load_turn_trace', lambda _session_id, _turn_id: {})

    result = regenerate_turn.delete_latest_turn('session')

    assert result['error']['code'] == 'TURN_TRACE_MISSING'
