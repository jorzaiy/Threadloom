#!/usr/bin/env python3
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

event_ledger = importlib.import_module('event_ledger')
model_config = importlib.import_module('model_config')
state_keeper = importlib.import_module('state_keeper')


def test_state_keeper_runtime_has_large_output_floor(monkeypatch):
    monkeypatch.setattr(model_config, '_global_runtime_store', lambda: {
        'model_defaults': {
            'narrator': {'max_output_tokens': 1},
            'state_keeper': {'max_output_tokens': 480},
        }
    })
    monkeypatch.setattr(model_config, 'load_user_model_store', lambda: {
        'narrator': {'model': 'narrator-model'},
        'state_keeper': {'model': 'keeper-model'},
        'advanced_models': {},
        'active_preset': 'world-sim-core',
    })

    cfg = model_config.load_runtime_config()

    assert cfg['models']['state_keeper']['max_output_tokens'] >= 3000
    assert cfg['models']['state_keeper_candidate']['max_output_tokens'] >= 3000


def test_state_keeper_retries_truncated_unparseable_output(monkeypatch):
    calls = []
    replies = [
        ('not json and no state fields', {'finish_reason': 'length'}),
        ('{"time":"辰时", "location":"药铺", "main_event":"陆小环买药后离开药铺。", "immediate_goal":"观察药铺外动静。", "onstage_npcs":["灵貂"], "carryover_clues":["年轻男人鞋面有暗红泥屑。"]}', {'finish_reason': 'stop'}),
    ]

    def fake_call_role_llm(_role, _system, prompt):
        calls.append(prompt)
        return replies.pop(0)

    monkeypatch.setattr(state_keeper, 'call_role_llm', fake_call_role_llm)

    reply, usage, attempts = state_keeper._call_state_keeper_llm('base prompt')

    assert attempts == 2
    assert usage['retry_count'] == 1
    assert '更紧凑的严格 JSON' in calls[1]
    assert '陆小环买药后离开药铺' in reply


def test_state_keeper_accepts_recoverable_truncated_payload(monkeypatch):
    reply_text = 'prefix {"time":"辰时", "location":"药铺", "main_event":"陆小环买药后离开药铺。", "immediate_goal":"观察药铺外动静。", "onstage_npcs":["灵貂"], "carryover_clues":["年轻男人鞋面有暗红泥屑。"]} trailing'

    monkeypatch.setattr(
        state_keeper,
        'call_role_llm',
        lambda *_args: (reply_text, {'finish_reason': 'length'}),
    )

    reply, usage, attempts = state_keeper._call_state_keeper_llm('base prompt')

    assert attempts == 1
    assert usage['truncated_output'] is True
    assert usage['partial_payload_used'] is True
    assert '陆小环买药后离开药铺' in reply


def test_event_anchor_can_disable_stale_fallbacks():
    time_anchor, location_anchor = event_ledger.extract_time_location_anchor(
        '陆小环把药包收好，转身离开药铺。',
        fallback_time='',
        fallback_location='',
    )

    assert time_anchor == ''
    assert location_anchor == ''


def test_event_anchor_uses_explicit_header_without_fallbacks():
    time_anchor, location_anchor = event_ledger.extract_time_location_anchor(
        '九幽历三千七百二十二年，四月十七，辰时。人界，青石镇，主街药铺。\n\n陆小环把药包收好。',
        fallback_time='',
        fallback_location='',
    )

    assert time_anchor == '九幽历三千七百二十二年，四月十七，辰时'
    assert location_anchor == '人界，青石镇，主街药铺'
