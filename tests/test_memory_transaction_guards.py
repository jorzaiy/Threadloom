#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import pytest

import mid_context_agent
import event_ledger
import runtime_store
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


def test_state_keeper_prompt_forbids_promoting_user_hypothesis():
    prompt = state_keeper.STATE_KEEPER_FILL_SYSTEM

    assert '提问、猜测、类比、求证或推理' in prompt
    assert '不得把它写成 carryover_signals' in prompt
    assert '必须保留不确定性' in prompt
    assert '不得改写成“已经证实' in prompt


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


def test_state_keeper_fill_can_replace_stale_current_scene_core_fields():
    baseline = {
        'time': '清晨',
        'location': '青州城北门巷道客栈',
        'main_event': '灰眼珠子看着她',
        'immediate_goal': '在聚灵阵辅助下继续吐纳修炼，恢复丹田灵力。',
        'onstage_npcs': [],
        'knowledge_scope': {},
    }
    payload = state_keeper._coerce_state_payload({
        'main_event': '陆小环进入灰眼男人房间，看见桌上符纸朱砂和外衫暗袋。',
        'immediate_goal': '回答灰眼男人追问铜片来历。',
        'onstage_npcs': ['灰眼男人'],
        'scene_entities': [{'primary_label': '灰眼男人', 'aliases': ['灰眼男人'], 'role_label': '当前互动人物', 'onstage': True}],
        'knowledge_scope': {
            'npc_local': {
                '青布衫中年人': {'learned': ['房内有制符材料及暗袋']},
                '灰眼男人': {'learned': ['陆小环拿着铜片']},
            }
        },
        'turn_event_summary': {
            'summary': '陆小环进了灰眼男人房间，看见符纸朱砂和外衫暗袋。',
            'actors': ['灰眼男人'],
            'objects': ['符纸', '朱砂', '外衫暗袋'],
            'clues': ['灰眼男人会制符'],
            'scene_shift': True,
        },
    }, baseline_state=baseline)

    merged = state_keeper._merge_keeper_fill(baseline, payload)

    assert merged['immediate_goal'] == '回答灰眼男人追问铜片来历。'
    assert merged['onstage_npcs'] == ['灰眼男人']
    assert merged['_current_turn_onstage_npcs'] == ['灰眼男人']
    assert merged['scene_entities'][0]['primary_label'] == '灰眼男人'
    assert '青布衫中年人' not in merged.get('knowledge_scope', {}).get('npc_local', {})
    assert merged['knowledge_scope']['npc_local']['灰眼男人']['learned'] == ['陆小环拿着铜片']
    assert merged['turn_event_summary']['objects'] == ['符纸', '朱砂', '外衫暗袋']


def test_state_keeper_persona_patches_are_actor_id_bound_and_validated():
    baseline = {
        'actors': {
            'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '陆小环'},
            'npc_006': {'actor_id': 'npc_006', 'kind': 'npc', 'name': '灰眼男人', 'aliases': ['二楼倒数第二间屋的客人']},
            'npc_002': {'actor_id': 'npc_002', 'kind': 'npc', 'name': '青布衫的中年人', 'aliases': []},
        },
        'actor_persona_hooks': {
            'npc_006': {'speech_style': '短句、低声', 'mannerisms': ['盯着铜片看']},
        },
    }
    payload = state_keeper._coerce_state_payload({
        'persona_patches': [
            {
                'actor_id': 'npc_006',
                'display_name': '二楼倒数第二间屋的客人',
                'speech_style': '话少，句子短，常压低声音。',
                'behavior_mode': '先观察对方拿出的物件，再决定是否开口。',
                'decision_bias': '优先确认对方掌握的信息来源。',
                'mannerisms': ['目光会在铜片豁口处停留', '靠门板挡住房内东西'],
                'stress_response': '受试探时不解释，反问对方看到了什么。',
                'evidence': '他说“那东西，哪捡的。”',
                'confidence': 0.5,
            },
            {
                'actor_id': 'npc_002',
                'display_name': '灰眼男人',
                'speech_style': '错误归属应被丢弃。',
            },
            {
                'actor_id': 'protagonist',
                'display_name': '陆小环',
                'speech_style': '主角不写入 NPC persona。',
            },
            {
                'actor_id': 'npc_006',
                'speech_style': '缺 display_name 应被丢弃。',
            },
            {
                'actor_id': 'npc_006',
                'display_name': '男人',
                'speech_style': '宽泛子串不应匹配灰眼男人。',
            },
        ],
    }, baseline_state=baseline)

    merged = state_keeper._merge_keeper_fill(baseline, payload)

    hooks = merged['actor_persona_hooks']
    assert hooks['npc_006']['speech_style'] == '话少，句子短，常压低声音。'
    assert hooks['npc_006']['behavior_mode'] == '先观察对方拿出的物件，再决定是否开口。'
    assert '缺 display_name' not in hooks['npc_006']['speech_style']
    assert '宽泛子串' not in hooks['npc_006']['speech_style']
    assert hooks['npc_006']['mannerisms'][-2:] == ['目光会在铜片豁口处停留', '靠门板挡住房内东西']
    assert 'npc_002' not in hooks
    assert 'protagonist' not in hooks


def test_unified_event_ledger_uses_keeper_turn_event_summary_without_llm(monkeypatch):
    monkeypatch.setattr(event_ledger, 'call_model', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('no extra llm')))

    ledger = event_ledger.build_event_ledger_with_llm(
        user_text='进去看看',
        narrator_reply='她进了灰眼男人房间。黄纸摊着三四张，边角压着朱砂碟。床沿外衫里子缝了个暗袋。',
        prev_state={'location': '走廊'},
        onstage_names=['灰眼男人'],
        location='灰眼男人房间',
        keeper_signals={
            'main_event': '陆小环进入灰眼男人房间，发现符纸朱砂和外衫暗袋。',
            'turn_event_summary': {
                'summary': '陆小环进入灰眼男人房间，发现黄纸、朱砂碟和外衫暗袋。',
                'actors': ['灰眼男人'],
                'objects': ['黄纸', '朱砂碟', '外衫暗袋'],
                'clues': ['灰眼男人房中有制符材料'],
                'scene_shift': True,
            },
        },
        use_llm=False,
    )
    item = event_ledger.build_event_summary_item(
        turn_id='turn-0089',
        ledger=ledger,
        onstage_names=['灰眼男人'],
        narrator_reply='她进了灰眼男人房间。黄纸摊着三四张，边角压着朱砂碟。床沿外衫里子缝了个暗袋。',
    )

    assert ledger['provider'] == 'unified_extraction'
    assert '黄纸' in item['summary']
    assert item['actors'] == ['灰眼男人']
    assert item['objects'] == ['黄纸', '朱砂碟', '外衫暗袋']


def test_unified_event_summary_rejects_single_bigram_overlap():
    ledger = {
        'provider': 'unified_extraction',
        'summary_text': '远处山门忽然塌陷，青衣道人召出雷火。',
        'main_event_candidates': [{'text': '灰眼男人房间内谈话。'}],
        'scene_shift': {'changed': False},
        'fallback_heuristic': {'summary_text': '灰眼男人看向铜片。'},
    }

    item = event_ledger.build_event_summary_item(
        turn_id='turn-0090',
        ledger=ledger,
        onstage_names=['灰眼男人'],
        narrator_reply='灰眼男人看向铜片，问她从哪里捡到。',
    )

    assert item['summary'] == '灰眼男人看向铜片。'


def test_unified_event_ledger_requires_turn_event_summary_when_requested():
    ledger = event_ledger.build_event_ledger_with_llm(
        user_text='继续',
        narrator_reply='掌柜低声说明账册已经被人取走，线索转向后院。',
        prev_state={'location': '前厅'},
        onstage_names=['掌柜'],
        location='前厅',
        current_state={'carryover_signals': [{'type': 'clue', 'text': '账册被人取走'}]},
        keeper_signals={'main_event': '清晨，前厅'},
        use_llm=False,
        require_turn_event_summary=True,
    )

    assert ledger['provider'] == 'heuristic'
    assert ledger['summary_text'] != '清晨，前厅'


def test_event_summary_upsert_replaces_existing_turn(tmp_path, monkeypatch):
    paths = {'event_summaries': tmp_path / 'event_summaries.json'}
    monkeypatch.setattr(runtime_store, 'session_paths', lambda _session_id: paths)
    runtime_store.save_event_summaries('session', {
        'version': 1,
        'items': [{'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '旧摘要'}],
    })

    runtime_store.upsert_event_summary('session', {'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '新摘要'})

    payload = runtime_store.load_event_summaries('session')
    assert payload['items'] == [{'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '新摘要'}]
