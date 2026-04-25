#!/usr/bin/env python3
"""End-to-end card import test: build a synthetic v2 + v3 SillyTavern card,
run import_card_bundle into a tmp dir, then assert all 5 output JSONs are
shaped correctly and field-complete.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import card_importer as ci  # noqa: E402
from character_assets import (  # noqa: E402
    character_core_path,
    import_manifest_path,
    lorebook_path,
    openings_path,
    set_character_override_root,
    clear_character_override_root,
    system_npcs_path,
)


def _build_v3_card() -> dict:
    return {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'data': {
            'name': '李逍遥',
            'nickname': '逍遥',
            'description': '一名寻找仙缘的少年侠客。' * 30,
            'personality': '活泼机敏,重情重义。' * 60,
            'scenario': '南诏国边境,战乱将起。',
            'first_mes': '你睁开眼,发现自己倒在客栈大堂。',
            'mes_example': '<START>\n{{user}}: 你是谁?\n{{char}}: 在下李逍遥。',
            'system_prompt': 'You are roleplaying as 李逍遥.' * 50,
            'post_history_instructions': '请保持仙侠口吻。',
            'creator_notes': 'Inspired by 仙剑奇侠传.',
            'creator_notes_multilingual': {'en': 'EN notes', 'zh': '中文备注'},
            'creator': 'Test Author',
            'character_version': '1.3',
            'tags': ['仙侠', '武侠', 'rpg'],
            'talkativeness': '0.6',
            'creation_date': 1700000000,
            'modification_date': 1710000000,
            'extensions': {'depth_prompt': {'depth': 4}, 'fav': True},
            'alternate_greetings': [
                '客栈：你在客栈醒来。',
                '客栈深夜：半夜被怪声惊醒。',
            ],
            'group_only_greetings': ['群聊：江湖众人围坐。'],
            'character_book': {
                'name': '南诏世界书',
                'description': 'Lore for the southern frontier.',
                'scan_depth': 4,
                'token_budget': 2000,
                'recursive_scanning': True,
                'extensions': {'world': '南诏'},
                'entries': [
                    {
                        'id': 1,
                        'keys': ['南诏'],
                        'secondary_keys': ['国境'],
                        'content': '南诏是一个边境小国,与大理多有摩擦。',
                        'comment': '南诏概述',
                        'enabled': True,
                        'constant': True,
                        'selective': False,
                        'position': 'before_char',
                        'depth': 4,
                        'probability': 100,
                        'useProbability': False,
                        'group': 'world',
                        'extensions': {'role': 'world'},
                        'insertion_order': 100,
                    },
                    {
                        'id': 2,
                        'keys': ['林月如'],
                        'content': '李逍遥的青梅竹马,豪爽直率。',
                        'comment': 'NPC：林月如',
                        'constant': False,
                        'enabled': True,
                        'selective': True,
                        'selectiveLogic': 0,
                        'position': 'after_char',
                        'case_sensitive': False,
                        'match_whole_words': True,
                        'depth': 2,
                        'probability': 80,
                        'useProbability': True,
                    },
                    {
                        'id': 3,
                        'keys': ['触发器'],
                        'content': '',
                        'comment': '空内容仅触发',
                        'enabled': True,
                    },
                    {
                        'id': 4,
                        'keys': ['cast'],
                        'content': '\n'.join([
                            '## 阿牛',
                            '身份: 樵夫',
                            '外貌: 朴实壮硕',
                            '',
                            '## 王婆',
                            '身份: 客栈老板娘',
                            '外貌: 慈眉善目',
                        ]),
                        'comment': '次要人物',
                        'enabled': True,
                    },
                ],
            },
        },
    }


def test_e2e_v3_card_import_full_outputs():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / 'source'
        target.mkdir(parents=True)
        set_character_override_root(target)
        try:
            card = _build_v3_card()
            report = ci.import_card_bundle(card, png_data=None)

            # 1. report shape
            assert report['success'] is True
            assert report['name'] == '李逍遥'
            assert report['lorebook_entries_count'] >= 3
            assert report['system_npcs_count'] >= 1
            assert report['opening_options_count'] >= 1

            # 2. character-data.json
            core = json.loads(character_core_path().read_text(encoding='utf-8'))
            assert core['name'] == '李逍遥'
            assert core['nickname'] == '逍遥'
            assert 'mes_example' in core and core['mes_example']
            assert core['post_history_instructions'] == '请保持仙侠口吻。'
            assert core['tags'] == ['仙侠', '武侠', 'rpg']
            assert core['character_version'] == '1.3'
            assert core['talkativeness'] == '0.6'
            assert core['creator_notes_multilingual'] == {'en': 'EN notes', 'zh': '中文备注'}
            assert core['extensions'] == {'depth_prompt': {'depth': 4}, 'fav': True}
            assert core['source']['creator'] == 'Test Author'
            assert core['source']['creation_date'] == '1700000000'
            assert len(core['role']) > 240, "personality should not be truncated to 240 chars"
            assert 'system_summary' in core

            # 3. lorebook.json
            book = json.loads(lorebook_path().read_text(encoding='utf-8'))
            assert book['name'] == '南诏世界书'
            assert book['scan_depth'] == 4
            assert book['recursive_scanning'] is True
            assert book['extensions'] == {'world': '南诏'}
            entries = book['entries']
            nanchao = next(e for e in entries if '南诏' in e['title'])
            assert nanchao['alwaysOn'] is True
            assert nanchao['position'] == 'before_char'
            assert nanchao['depth'] == 4
            assert nanchao['probability'] == 100
            assert nanchao['extensions'] == {'role': 'world'}
            linyueru = next(e for e in entries if '林月如' in e['title'])
            assert linyueru['selective'] is True
            assert linyueru['caseSensitive'] is False
            assert linyueru['matchWholeWords'] is True
            assert linyueru['probability'] == 80
            assert linyueru['useProbability'] is True
            # keyword-only entry retained
            assert any('空内容仅触发' in e['title'] for e in entries)

            # 4. openings.json
            openings = json.loads(openings_path().read_text(encoding='utf-8'))
            kinds = {opt.get('kind') for opt in openings.get('options', [])}
            assert 'group_only_greeting' in kinds
            assert 'alternate_greeting' in kinds

            # 5. system-npcs.json
            npcs = json.loads(system_npcs_path().read_text(encoding='utf-8'))
            names = {item['name'] for item in npcs.get('items', [])}
            assert '李逍遥' in names  # card primary
            # roster-only items (阿牛/王婆) must be in items now (P0-1)
            roster_names = {item['name'] for item in npcs.get('roster', [])}
            assert roster_names.issubset(names), "roster names should be in items[]"

            # 6. import-manifest.json
            manifest = json.loads(import_manifest_path().read_text(encoding='utf-8'))
            assert manifest['card_name'] == '李逍遥'
            assert manifest['source']['creator'] == 'Test Author'
            assert manifest['stats']['raw_lorebook_entries'] >= 4
            assert manifest['stats']['system_npcs'] >= 1
        finally:
            clear_character_override_root()


def test_e2e_english_card_import():
    """Pure English / latin card: must still produce a valid bundle."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / 'source'
        target.mkdir(parents=True)
        set_character_override_root(target)
        try:
            card = {
                'spec': 'chara_card_v2',
                'spec_version': '2.0',
                'data': {
                    'name': 'Aria Stark',
                    'description': 'A noble of the North.',
                    'personality': 'Brave and headstrong.',
                    'scenario': 'Civil war approaches.',
                    'first_mes': 'You meet a young woman in a tavern.',
                    'tags': ['fantasy'],
                    'character_book': {
                        'entries': [
                            {
                                'id': 0,
                                'keys': ['cast'],
                                'content': '\n'.join([
                                    '# Aria Stark',
                                    'A noble of the North.',
                                    '',
                                    '# Captain Olen',
                                    'A grizzled veteran.',
                                ]),
                                'comment': 'Cast',
                            },
                        ],
                    },
                },
            }
            report = ci.import_card_bundle(card, png_data=None)
            assert report['success'] is True
            assert report['name'] == 'Aria Stark'

            npcs = json.loads(system_npcs_path().read_text(encoding='utf-8'))
            names = {it['name'] for it in npcs.get('items', [])}
            # Either via _maybe_add_card_primary_npc or via embedded latin extractor
            assert 'Aria Stark' in names
            assert 'Captain Olen' in names, f"expected 'Captain Olen' in {names}"
        finally:
            clear_character_override_root()


def test_e2e_idempotent_on_reimport():
    """Re-importing the same card overwrites cleanly without partial state."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / 'source'
        target.mkdir(parents=True)
        set_character_override_root(target)
        try:
            card = _build_v3_card()
            r1 = ci.import_card_bundle(card, png_data=None)
            r2 = ci.import_card_bundle(card, png_data=None)
            assert r1['name'] == r2['name']
            assert r1['lorebook_entries_count'] == r2['lorebook_entries_count']
            assert r1['system_npcs_count'] == r2['system_npcs_count']
        finally:
            clear_character_override_root()


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
