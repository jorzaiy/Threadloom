#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import json

from context_builder import _slim_character_core, load_lorebook_source_hits, select_lorebook_text_for_turn, select_recent_history_window, summarize_lorebook_entries  # noqa: E402
from narrator_input import _format_recent_window  # noqa: E402


def test_recent_history_keeps_opening_assistant_before_first_pair():
    opening = {'role': 'assistant', 'content': '训练场开局。'}

    assert select_recent_history_window([opening], 12) == [opening]
    assert _format_recent_window([opening], 12) == '[叙事] 训练场开局。'


def test_recent_history_still_keeps_complete_pairs():
    opening = {'role': 'assistant', 'content': '训练场开局。'}
    user = {'role': 'user', 'content': '继续跑'}
    assistant = {'role': 'assistant', 'content': '跑步继续。', 'completion_status': 'complete'}

    assert select_recent_history_window([opening, user, assistant], 12) == [opening, user, assistant]


def test_opening_lorebook_turn_prefers_full_source_summary_over_index():
    content = 'World_Setting: 现代架空\n' + ('背景。' * 120) + '\n- 学院为男校，不存在恋爱氛围'
    source_summary = summarize_lorebook_entries(
        [{'id': '1', 'title': '世界观', 'content': content}],
        max_entry_chars=6000,
        max_total_chars=12000,
    )
    index_hits = {'text': '压缩索引：现代架空。', 'items': [{'id': 'idx'}]}

    text = select_lorebook_text_for_turn(source_summary, index_hits, opening_lorebook_turn=True)

    assert '学院为男校，不存在恋爱氛围' in text
    assert '压缩索引' not in text


def test_non_opening_lorebook_turn_prefers_index_hits():
    source_summary = {'text': '完整原文世界书'}
    index_hits = {'text': '压缩索引世界书', 'items': [{'id': 'idx'}]}

    assert select_lorebook_text_for_turn(
        source_summary,
        index_hits,
        opening_lorebook_turn=False,
        lorebook_source_hits={'text': '', 'items': []},
    ) == '压缩索引世界书'


def test_non_opening_lorebook_turn_prefers_source_hits_over_index(tmp_path):
    lorebook_path = tmp_path / 'lorebook.json'
    lorebook_path.write_text(json.dumps({
        'entries': [
            {
                'id': 'academy',
                'title': '学院规则',
                'content': 'Academy:\n- 学院为男校，不存在恋爱氛围\n- 训练场分区开放',
            }
        ]
    }, ensure_ascii=False), encoding='utf-8')
    index_hits = {
        'text': '蒸馏摘要：学院规则。',
        'items': [
            {
                'id': 'lore-academy',
                'source_entry_ids': ['academy'],
                'score': 8,
                'keyword_hits': ['学院'],
            }
        ],
    }

    source_hits = load_lorebook_source_hits(lorebook_path, index_hits, max_entry_chars=500, max_total_chars=1000)
    text = select_lorebook_text_for_turn(
        {'text': '完整候选摘要'},
        index_hits,
        opening_lorebook_turn=False,
        lorebook_source_hits=source_hits,
    )

    assert '学院为男校，不存在恋爱氛围' in text
    assert '蒸馏摘要' not in text
    assert source_hits['items'][0]['id'] == 'academy'


def test_slim_character_core_preserves_world_constraint_fields():
    data = {
        'name': '维克托',
        'description': '现代角色。',
        'relationshipToUser': '同校学生',
        'goals': ['保持身份迷雾'],
        'mustRemember': ['主世界是现代校园。'],
        'worldMechanics': {'identityFog': '身份不会自动公开'},
        'system_summary': '现代架空校园。',
        'coreDescription': {
            'summary': '现代现实语境。',
            'genre': '现代校园',
            'era': '现代',
            'unused': 'drop',
        },
        'hints': {
            'runtimeRules': ['不要切换题材'],
            'time_era_prefix': '现代公历',
            'forbiddenContradictions': ['不引入异世界规则'],
            'unused': 'drop',
        },
        'speakingStyle': {
            'tone': '冷静',
            'taboos': ['古风腔'],
            'unused': 'drop',
        },
    }

    slim = _slim_character_core(data)

    assert slim['relationshipToUser'] == '同校学生'
    assert slim['worldMechanics']['identityFog'] == '身份不会自动公开'
    assert slim['mustRemember'] == ['主世界是现代校园。']
    assert slim['coreDescription']['genre'] == '现代校园'
    assert slim['hints']['time_era_prefix'] == '现代公历'
    assert slim['speakingStyle']['taboos'] == ['古风腔']
    assert 'unused' not in slim['coreDescription']
    assert 'unused' not in slim['hints']
    assert 'unused' not in slim['speakingStyle']
