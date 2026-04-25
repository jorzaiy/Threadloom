#!/usr/bin/env python3
"""Unit tests for card_importer field extraction & system NPC heuristics.

Covers fixes from doc/audit/CARD-IMPORT-AUDIT.md:
  P0-1 system_npcs.items now includes roster
  P0-2 SillyTavern v2/v3 fields preserved
  P0-3 personality / summary / system_prompt truncation widened + boundary-aware
  P1-5 _infer_faction is data-driven (not inline hardcoded)
  P1-6 hardcoded blocklist replaced with _looks_like_template_token
  P1-7 _maybe_add_card_primary_npc accepts longer names + ascii-only names
  P1-8 _extract_embedded_npcs_latin handles English NPC blocks
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import card_importer as ci  # noqa: E402


# ---------- helpers ----------------------------------------------------------

def _wrap_v2(payload: dict) -> dict:
    return {'spec': 'chara_card_v2', 'spec_version': '2.0', 'data': payload}


def _wrap_v3(payload: dict) -> dict:
    return {'spec': 'chara_card_v3', 'spec_version': '3.0', 'data': payload}


def _make_book_entry(**overrides) -> dict:
    base = {
        'id': '0',
        'keys': ['hero'],
        'content': 'Hero of the realm.',
        'comment': 'Hero',
        'enabled': True,
        'constant': False,
    }
    base.update(overrides)
    return base


# ---------- P0-2: character core field preservation -------------------------

def test_character_core_preserves_v2_fields():
    payload = {
        'name': 'Aria',
        'description': 'desc',
        'personality': 'p' * 1500,
        'scenario': 'sc',
        'mes_example': 'EX1\nEX2',
        'post_history_instructions': 'jailbreak',
        'tags': ['fantasy', 'romance'],
        'character_version': '1.2',
        'creator': 'someone',
        'creator_notes': 'notes',
        'talkativeness': '0.5',
        'nickname': 'Ari',
        'extensions': {'depth_prompt': {'depth': 4}},
    }
    core = ci._extract_character_core(_wrap_v2(payload))
    assert core['name'] == 'Aria'
    assert core['nickname'] == 'Ari'
    assert core['mes_example'] == 'EX1\nEX2'
    assert core['post_history_instructions'] == 'jailbreak'
    assert core['tags'] == ['fantasy', 'romance']
    assert core['character_version'] == '1.2'
    assert core['talkativeness'] == '0.5'
    assert core['source']['creator'] == 'someone'
    assert core['extensions'] == {'depth_prompt': {'depth': 4}}


def test_character_core_accepts_string_tags():
    payload = {'name': 'X', 'tags': 'a, b, c'}
    core = ci._extract_character_core(_wrap_v2(payload))
    assert core['tags'] == ['a', 'b', 'c']


def test_character_core_handles_v3_extras():
    payload = {
        'name': 'X',
        'creator_notes_multilingual': {'en': 'EN', 'zh': '中文'},
        'creation_date': 1700000000,
        'modification_date': 1710000000,
    }
    core = ci._extract_character_core(_wrap_v3(payload))
    assert core['creator_notes_multilingual'] == {'en': 'EN', 'zh': '中文'}
    assert core['source']['creation_date'] == '1700000000'
    assert core['source']['modification_date'] == '1710000000'


# ---------- P0-3: truncation now boundary-aware & wider ---------------------

def test_personality_no_longer_truncated_at_240():
    long_personality = 'a' * 1400
    payload = {'name': 'X', 'personality': long_personality}
    core = ci._extract_character_core(_wrap_v2(payload))
    assert len(core['role']) >= 1400, f"personality should fit ~1500 limit, got {len(core['role'])}"


def test_summary_truncation_widened():
    payload = {
        'name': 'X',
        'description': 'd' * 1500,
        'scenario': 's' * 1500,
    }
    core = ci._extract_character_core(_wrap_v2(payload))
    summary = core['coreDescription']['summary']
    assert len(summary) > 1200, f"summary should now exceed old 1200-char limit, got {len(summary)}"


# ---------- P0-2: lorebook entry field preservation -------------------------

def test_lorebook_entry_preserves_full_metadata():
    raw = _make_book_entry(
        id='42',
        keys=['hero', 'champion'],
        secondary_keys=['warrior'],
        content='The hero rises.',
        constant=True,
        selective=True,
        selective_logic=2,
        position='before_char',
        case_sensitive=True,
        match_whole_words=True,
        depth=5,
        probability=80,
        useProbability=True,
        group='boss',
        groupOverride=True,
        groupWeight=10,
        vectorized=False,
        disable=False,
        extensions={'role': 'hero'},
    )
    converted = ci._convert_lorebook_entry(raw)
    assert converted['selective'] is True
    assert converted['selectiveLogic'] == 2
    assert converted['position'] == 'before_char'
    assert converted['caseSensitive'] is True
    assert converted['matchWholeWords'] is True
    assert converted['depth'] == 5
    assert converted['probability'] == 80
    assert converted['useProbability'] is True
    assert converted['group'] == 'boss'
    assert converted['groupOverride'] is True
    assert converted['groupWeight'] == 10
    assert converted['extensions'] == {'role': 'hero'}
    assert converted['secondary_keywords'] == ['warrior']


def test_lorebook_keeps_keyword_only_entry():
    """Entries with empty content but valid keywords used to be silently
    dropped — they are now retained because they may be linked-trigger only."""
    raw = _make_book_entry(content='', keys=['linktrigger'], comment='LinkTrigger')
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'name': 'Book', 'entries': [raw]},
    }))
    titles = [e['title'] for e in book['entries']]
    assert 'LinkTrigger' in titles


def test_lorebook_top_level_metadata_preserved():
    raw_book = {
        'name': 'World Lore',
        'description': 'Top-level lore book',
        'scan_depth': 4,
        'token_budget': 2048,
        'recursive_scanning': True,
        'extensions': {'foo': 'bar'},
        'entries': [],
    }
    book = ci._extract_lorebook(_wrap_v2({'name': 'X', 'character_book': raw_book}))
    assert book['name'] == 'World Lore'
    assert book['description'] == 'Top-level lore book'
    assert book['scan_depth'] == 4
    assert book['token_budget'] == 2048
    assert book['recursive_scanning'] is True
    assert book['extensions'] == {'foo': 'bar'}


def test_lorebook_expands_embedded_json_entries_with_literal_newlines():
    raw = _make_book_entry(
        id='0',
        comment='世界观',
        keys=[],
        constant=True,
        content='''{
  "name": "血蚀纪",
  "entries": [
    {"keys": ["世界观"], "content": "第一行
第二行"},
    {"keys": ["Dynamic Rules"], "content": "丧尸或怪物会随机出现"}
  ]
}''',
    )
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'entries': [raw]},
    }))
    titles = [e['title'] for e in book['entries']]
    assert '世界观 / 世界观' in titles
    assert '世界观 / Dynamic Rules' in titles
    world = next(e for e in book['entries'] if e['title'] == '世界观 / 世界观')
    assert world['content'] == '第一行\n第二行'
    assert world['keywords'] == ['世界观']
    assert world['source_kind'] == 'embedded_lorebook_json'
    assert world['alwaysOn'] is True
    dynamic = next(e for e in book['entries'] if e['title'] == '世界观 / Dynamic Rules')
    assert dynamic['entryType'] == 'rule'


def test_lorebook_does_not_expand_plain_json_without_entries():
    raw = _make_book_entry(
        id='0',
        comment='全洁',
        keys=[],
        content='{"keys":["全洁定义"],"content":"规则文本"}',
    )
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'entries': [raw]},
    }))
    assert len(book['entries']) == 1
    assert book['entries'][0]['title'] == '全洁'


def test_lorebook_filters_embedded_initial_guide_from_runtime_lorebook():
    raw = _make_book_entry(
        id='0',
        comment='世界观',
        keys=[],
        constant=True,
        content='''{
  "name": "修仙世界设定",
  "entries": [
    {"keys": ["世界观"], "content": "九幽大陆背景。"},
    {"keys": ["初始引导"], "content": "请{{user}}设定姓名。"}
  ]
}''',
    )
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'entries': [raw]},
    }))
    filtered = ci._filter_runtime_lorebook_entries(book)
    titles = [e['title'] for e in filtered['entries']]
    assert '世界观 / 世界观' in titles
    assert all('初始引导' not in title for title in titles)


# ---------- P0-2: openings handles v3 group_only_greetings ------------------

def test_openings_includes_group_only_greetings():
    payload = {
        'name': 'X',
        'first_mes': 'Hello.',
        'alternate_greetings': ['Alt: another start'],
        'group_only_greetings': ['Group: tavern start'],
    }
    options = ci._extract_opening_options(payload)
    kinds = {opt.get('kind') for opt in options}
    assert 'first_mes' in kinds
    assert 'alternate_greeting' in kinds
    assert 'group_only_greeting' in kinds


def test_openings_alternate_greeting_split_safe_when_colon_in_body():
    """Old behavior: 'a: b: c' was split on first ':' and lost both halves
    of the body. Now we only split when the head is a short title."""
    payload = {
        'name': 'X',
        'first_mes': '',
        'alternate_greetings': ['Long body without short title prefix here, but containing: a colon mid-sentence'],
    }
    options = ci._extract_opening_options(payload)
    alt = next(o for o in options if o['kind'] == 'alternate_greeting')
    assert 'mid-sentence' in alt['full_text']


# ---------- P1-5: _infer_faction --------------------------------------------

def test_infer_faction_legacy_hint_still_works():
    assert ci._infer_faction('太子心腹', '') == '东宫'
    assert ci._infer_faction('', '镇北司军令') == '镇北司'


def test_infer_faction_returns_empty_for_generic_card():
    assert ci._infer_faction('Aria Stark', 'A noble of the North.') == ''


# ---------- P1-6: template-token heuristic ----------------------------------

def test_looks_like_template_token_catches_jinja():
    assert ci._looks_like_template_token('{{user.name}}')
    assert ci._looks_like_template_token('{% if x %}')
    assert ci._looks_like_template_token('[EVENT]meet')
    assert ci._looks_like_template_token('user.relationships')
    assert ci._looks_like_template_token('snake_case_id')
    assert ci._looks_like_template_token('')


def test_looks_like_template_token_does_not_falsely_block_real_names():
    assert not ci._looks_like_template_token('小美')   # Chinese given name
    assert not ci._looks_like_template_token('血蚀纪')  # Chinese setting name
    assert not ci._looks_like_template_token('Aria Stark')
    assert not ci._looks_like_template_token('Captain Olen')


# ---------- P1-7: card primary NPC accepts ascii / longer names -------------

def test_card_primary_npc_accepts_english_full_name():
    card = _wrap_v2({'name': 'Aria Stark', 'description': 'A noble of the North.'})
    npcs = ci._extract_system_npcs({'entries': []}, card)
    names = [it['name'] for it in npcs.get('items', [])]
    assert 'Aria Stark' in names


def test_card_primary_npc_rejects_world_name():
    card = _wrap_v2({'name': 'Some World Setting', 'description': '开放世界 setting'})
    npcs = ci._extract_system_npcs({'entries': []}, card)
    names = [it['name'] for it in npcs.get('items', [])]
    assert 'Some World Setting' not in names


def test_card_primary_npc_accepts_chinese_short_name():
    card = _wrap_v2({'name': '李逍遥', 'description': '一名年轻侠客。'})
    npcs = ci._extract_system_npcs({'entries': []}, card)
    names = [it['name'] for it in npcs.get('items', [])]
    assert '李逍遥' in names


# ---------- P1-8: latin embedded NPC extraction -----------------------------

def test_extract_embedded_npcs_latin_markdown_heading():
    entry = {
        'id': 'lore-1',
        'title': 'Cast',
        'content': '\n'.join([
            '# Aria Stark',
            'A noble of the North.',
            '',
            '# Captain Olen',
            'A grizzled veteran.',
        ]),
        'priority': 0,
    }
    book = {'entries': [entry]}
    card = _wrap_v2({'name': 'Some Card', 'description': '', 'character_book': {'entries': []}})
    out = ci._extract_system_npcs(book, card)
    names = {it['name'] for it in out.get('items', [])}
    assert 'Aria Stark' in names
    assert 'Captain Olen' in names


def test_extract_embedded_npcs_latin_skips_cjk_dominant_content():
    """If content is mostly Chinese, don't run latin extractor (would
    misfire on isolated English words)."""
    entry = {
        'id': '1',
        'title': '人物',
        'content': '人物列表:\n李逍遥, a young warrior.\n林月如, his cousin.',
        'priority': 0,
    }
    card = _wrap_v2({'name': 'X'})
    out = ci._extract_system_npcs({'entries': [entry]}, card)
    names = {it['name'] for it in out.get('items', [])}
    # The latin extractor should not pull "a young warrior" as an NPC
    assert 'A' not in names
    assert 'A Young Warrior' not in names


# ---------- P0-1: items field now includes roster ---------------------------

def test_system_npcs_items_includes_all_buckets():
    # Build a lorebook entry that produces a roster-style npc (short Chinese
    # name without ·, no "门主"/"楼主"/etc.).
    entry = {
        'id': '1',
        'title': '次要人物',
        'content': '\n'.join([
            '阿牛',
            '身份: 樵夫',
            '外貌: 朴实',
        ]),
        'priority': 0,
    }
    card = _wrap_v2({'name': '主角'})
    out = ci._extract_system_npcs({'entries': [entry]}, card)
    items_count = len(out.get('items', []))
    bucket_count = len(out.get('core', [])) + len(out.get('faction_named', [])) + len(out.get('roster', []))
    assert items_count == bucket_count, f"items({items_count}) should include all buckets({bucket_count})"


# ---------- consumer-side: extract_system_npc_candidates --------------------

def test_extract_system_npc_candidates_falls_back_through_buckets(monkeypatch):
    sys.path.insert(0, str(ROOT / 'backend'))
    import context_builder as cb

    fake = {
        'core': [],
        'faction_named': [{'name': 'Faction Lord', 'role_label': 'leader', 'summary': 'x', 'priority': 50}],
        'roster': [{'name': 'Townsperson', 'role_label': 'civilian', 'summary': 'y', 'priority': 10}],
        'items': [],
    }
    monkeypatch.setattr(cb, 'load_system_npcs', lambda: fake)
    candidates = cb.extract_system_npc_candidates([], [], limit=5)
    names = [c['name'] for c in candidates]
    sources = {c['name']: c['source'] for c in candidates}
    assert 'Faction Lord' in names
    assert 'Townsperson' in names
    assert sources['Faction Lord'] == 'system_npc_faction'
    assert sources['Townsperson'] == 'system_npc_roster'


# ---------- ACU runtime cache: 重要人物条目X / 重要人物表-N ---------------

def test_important_person_entry_classified_as_archive_only():
    """SillyTavern Cyborg (TavernDB-ACU) writes runtime NPC dump back to
    character_book.entries as '重要人物条目1', '重要人物条目2', etc. — the
    importer must classify these as archive_only, same as '重要人物表-N'
    and '总结条目-N', so they don't pollute lorebook.json."""
    meta = ci._classify_lorebook_entry(
        title='重要人物条目1',
        content='| 维克托·奥古斯特 | 男/38岁 | … | 教官身份牌项链 | 否 | 20:45 暴力破门 |',
        keywords=[],
        always_on=False,
    )
    assert meta['runtimeScope'] == 'archive_only'
    assert meta['entryType'] in {'runtime_aux', 'runtime_dump'}

    meta_table = ci._classify_lorebook_entry(
        title='重要人物表-7',
        content='| 萧云铮 | 男/约20岁 | 一身锦袍 | 储物袋 | 否 | 暂离 |',
        keywords=[],
        always_on=False,
    )
    assert meta_table['runtimeScope'] == 'archive_only'


def test_important_person_entry_filtered_out_of_lorebook():
    raw = _make_book_entry(
        comment='重要人物条目1',
        content='| 阿牛 | 男 | 樵夫 | 柴刀 | 是 | 出场 |',
    )
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'entries': [raw]},
    }))
    titles_in_lorebook = [e['title'] for e in book['entries']]
    # entry is normalized into raw_lorebook with archive_only scope...
    assert any('重要人物条目1' == t for t in titles_in_lorebook)
    # ...but _filter_runtime_lorebook_entries removes it before write
    filtered = ci._filter_runtime_lorebook_entries(book)
    assert all('重要人物条目' not in (e.get('title') or '') for e in filtered['entries'])


def test_disabled_lorebook_entry_filtered_out_of_runtime_lorebook():
    raw = _make_book_entry(
        comment='user卡示例，可以在此基础上进行改动和使用，不要开启此条世界书',
        content='Name:\nAge: 18',
        enabled=False,
        constant=True,
    )
    book = ci._extract_lorebook(_wrap_v2({
        'name': 'X',
        'character_book': {'entries': [raw]},
    }))
    assert any(e.get('title') for e in book['entries'])
    filtered = ci._filter_runtime_lorebook_entries(book)
    assert filtered['entries'] == []


# ---------- self-reference filter for relationship_template -----------------

def test_relationship_template_skips_card_name():
    """When a card embeds 'name': '<card_name>' in a Jinja template entry
    (very common with [EVENT]meet and 人际 templates), the relationship
    extractor used to surface the card name itself as an NPC."""
    # Each NPC dict is its own block so the non-greedy regex in
    # _extract_template_relationship_npcs picks each up independently.
    content = """
{"name": "贺景", "type": "执政官", "personality": "稳重"}
{"name": "凌烨", "type": "指挥官", "personality": "冷峻"}
{"name": "血蚀纪", "type": "卡名", "personality": "should not surface"}
"""
    entry = {
        'id': 'meet-1',
        'title': 'meet',
        'content': content,
        'priority': 10,
    }
    card = _wrap_v3({
        'name': '血蚀纪',
        'description': '末世异能',
        'character_book': {'entries': []},
    })
    out = ci._extract_system_npcs({'entries': [entry]}, card)
    names = {it['name'] for it in out.get('items', [])}
    assert '贺景' in names
    assert '凌烨' in names
    assert '血蚀纪' not in names, "card name should not be surfaced as NPC"


def test_explicit_npc_with_user_template_is_not_filtered():
    """Explicit NPC lore often contains {{user}} relationship notes; those
    should not be treated as frontend/runtime templates and skipped."""
    entry = {
        'id': 'npc-1',
        'title': 'npc：月剑离',
        'content': '角色详情: 月剑离\n核心羁绊: {{user}}是他唯一的光和锚点。',
        'priority': 100,
    }
    card = _wrap_v3({'name': '碎影江湖', 'character_book': {'entries': []}})
    out = ci._extract_system_npcs({'entries': [entry]}, card)
    names = {it['name'] for it in out.get('items', [])}
    assert '月剑离' in names


# ---------- cover thumbnail generation --------------------------------------

def test_cover_small_is_actually_smaller_than_original(tmp_path, monkeypatch):
    """cover-small.png used to be a byte-identical copy of cover-original.png.
    With Pillow available it should now be a 320x320 center-cropped thumbnail."""
    from io import BytesIO
    from PIL import Image
    import character_assets

    # Build a real PNG (non-square so we exercise center crop)
    src = Image.new('RGB', (1024, 1536), color=(123, 45, 67))
    buf = BytesIO()
    src.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    monkeypatch.setattr(character_assets, '_CHARACTER_OVERRIDE_ROOT', tmp_path)
    monkeypatch.setattr(ci, 'character_assets_root', lambda: tmp_path / 'assets')

    result = ci._write_cover_assets(png_bytes, raw_card_hash='test')
    assert result['cover_saved']
    original = tmp_path / 'assets' / 'cover-original.png'
    small = tmp_path / 'assets' / 'cover-small.png'
    assert original.read_bytes() == png_bytes
    assert small.read_bytes() != png_bytes, "small must not be a byte-copy of original"
    with Image.open(small) as img:
        assert img.size == (320, 320), f"thumbnail should be 320x320, got {img.size}"
    assert small.stat().st_size < original.stat().st_size


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
