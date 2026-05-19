#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import pytest

import mid_context_agent
import event_ledger
import state_keeper


def test_mid_context_archive_objects_must_appear_in_window():
    pairs = [
        ({'content': '坐下喝茶'}, {'content': '小六子端来茶碗，掌柜在柜台后拨算盘。'}),
    ]
    digest = mid_context_agent._heuristic_digest(
        pairs,
        {
            'tracked_objects': [
                {'label': '门框之物', 'kind': 'artifact', 'story_relevant': True},
                {'label': '茶碗', 'kind': 'item', 'story_relevant': True},
            ],
        },
        'turn-0001',
        'turn-0001',
    )

    assert digest['tracked_objects'] == [{'label': '茶碗', 'kind': 'item'}]


def test_state_keeper_rejects_length_truncated_output(monkeypatch):
    monkeypatch.setattr(state_keeper, 'load_state', lambda _session_id: {'time': '上午', 'location': '茶肆', 'main_event': '对话', 'immediate_goal': '继续'})
    monkeypatch.setattr(state_keeper, 'seed_default_state', lambda _session_id: {'time': '待确认', 'location': '待确认', 'main_event': '待确认', 'immediate_goal': '待确认'})
    monkeypatch.setattr(state_keeper, 'call_role_llm', lambda *_args, **_kwargs: ('{"time":"上午"}', {'finish_reason': 'length'}))

    with pytest.raises(state_keeper.StateKeeperCallError):
        state_keeper.call_state_keeper('session', '正文', state_fragment={'time': '上午', 'location': '茶肆', 'main_event': '对话', 'immediate_goal': '继续'})


def test_unified_event_ledger_uses_heuristic_not_reverted_keeper_signal_shortcut():
    ledger = event_ledger.build_event_ledger_with_llm(
        user_text='继续追问',
        narrator_reply='掌柜低声说明账册已经被人取走，线索转向后院。',
        prev_state={'location': '前厅'},
        onstage_names=['掌柜'],
        location='前厅',
        current_state={'carryover_signals': [{'type': 'clue', 'text': '账册被人取走'}]},
        keeper_signals=None,
        use_llm=False,
    )

    assert ledger['provider'] == 'heuristic'


def test_reverted_keeper_signal_shortcut_still_available_only_when_explicit():
    ledger = event_ledger.build_event_ledger_with_llm(
        user_text='继续',
        narrator_reply='只是安静等待。',
        prev_state={'location': '前厅'},
        onstage_names=[],
        location='前厅',
        keeper_signals={'main_event': '不应在统一模式自动使用'},
        use_llm=False,
    )

    assert ledger['provider'] == 'keeper_signals'
