#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import json

from context_builder import _format_persona_profile_content, _slim_character_core, load_lorebook_source_hits, load_npc_profiles, npc_profile_load_audit, select_lorebook_text_for_turn, select_recent_history_window, summarize_lorebook_entries  # noqa: E402
from persona_runtime import build_persona_seed  # noqa: E402
from persona_updater import _observed_context  # noqa: E402
from runtime_store import save_persona_seed  # noqa: E402
from narrator_input import _format_recent_outline, _format_recent_window, build_narrator_input  # noqa: E402
from selector import summary_chunk_hits  # noqa: E402
from selector import profile_targets  # noqa: E402
from event_ledger import build_event_summary_item  # noqa: E402
from persona_updater import _valid_persona_token  # noqa: E402


def test_recent_history_keeps_opening_assistant_before_first_pair():
    opening = {'role': 'assistant', 'content': '训练场开局。'}

    assert select_recent_history_window([opening], 12) == [opening]
    assert _format_recent_window([opening], 12) == '[叙事] 训练场开局。'


def test_recent_history_still_keeps_complete_pairs():
    opening = {'role': 'assistant', 'content': '训练场开局。'}
    user = {'role': 'user', 'content': '继续跑'}
    assistant = {'role': 'assistant', 'content': '跑步继续。', 'completion_status': 'complete'}

    assert select_recent_history_window([opening, user, assistant], 12) == [opening, user, assistant]


def test_recent_outline_bridges_pairs_before_full_prose_window():
    history = []
    summaries = []
    for idx in range(1, 9):
        history.extend([
            {'role': 'user', 'content': f'用户动作{idx}'},
            {'role': 'assistant', 'content': f'叙事正文{idx}', 'completion_status': 'complete'},
        ])
        summaries.append({'turn_id': f'turn-{idx:04d}', 'summary': f'第{idx}轮提纲', 'actors': ['维克托'] if idx == 2 else []})

    outline = _format_recent_outline(summaries, history, full_pairs=6)
    full = _format_recent_window(history, limit_pairs=6)

    assert 'turn-0001: 第1轮提纲' in outline
    assert 'turn-0002: 第2轮提纲' in outline
    assert '人物=维克托' in outline
    assert '第3轮提纲' not in outline
    assert '用户动作2' not in full
    assert '用户动作3' in full
    assert '叙事正文8' in full


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


def test_npc_profile_load_audit_explains_missing_targets(tmp_path):
    npc_dir = tmp_path / 'npcs'
    npc_dir.mkdir()
    (npc_dir / '维克托.md').write_text('教官档案', encoding='utf-8')

    loaded = load_npc_profiles(npc_dir, ['韩骁'])
    audit = npc_profile_load_audit(npc_dir, ['韩骁'], loaded)

    assert loaded == []
    assert audit['reason'] == 'target_profile_missing'
    assert audit['missing'] == ['韩骁']
    assert audit['available_profile_names'] == ['维克托']


def test_npc_profile_load_audit_reports_loaded_targets(tmp_path):
    npc_dir = tmp_path / 'npcs'
    npc_dir.mkdir()
    (npc_dir / '韩骁.md').write_text('临时搭档档案', encoding='utf-8')

    loaded = load_npc_profiles(npc_dir, ['韩骁'])
    audit = npc_profile_load_audit(npc_dir, ['韩骁'], loaded)

    assert loaded[0]['name'] == '韩骁'
    assert audit['reason'] == 'loaded'
    assert audit['missing'] == []


def test_session_persona_json_loads_as_npc_profile_when_targeted(tmp_path, monkeypatch):
    session_root = tmp_path / 'runtime-data' / 'sessions'
    monkeypatch.setenv('THREADLOOM_RUNTIME_DATA_DIR', str(tmp_path / 'runtime-data'))
    # paths are resolved from env at import time in normal app flow; patch direct resolver for this focused unit.
    import runtime_store

    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)
    seed = {
        'display_name': '测试甲',
        'seed_layer': 'longterm',
        'identity': {'role_label': '线索提供者', 'faction': '本地', 'base_region': '前厅'},
        'persona_seed': {'archetype': {'value': '谨慎协助者'}, 'runtime_hooks': {'speech_rhythm': {'value': '短句'}}},
        'observations': {'recent_behavior': '测试甲低声提醒主角保管账册。'},
    }
    save_persona_seed('generic-session', 'longterm', seed)

    loaded = load_npc_profiles(tmp_path / 'missing-npcs', ['测试甲'], session_id='generic-session')

    assert loaded[0]['name'] == '测试甲'
    assert loaded[0]['source'] == 'session_persona'
    assert '线索提供者' in loaded[0]['content']
    assert '测试甲低声提醒主角保管账册' in loaded[0]['content']


def test_persona_seed_accumulates_recent_behavior_fields_from_observed_turns():
    history = [
        {'role': 'user', 'content': '询问测试乙的看法'},
        {'role': 'assistant', 'content': '测试乙穿着灰色外套，手指有旧疤。测试乙先观察门口，再低声提醒主角别急着打开包裹。'},
    ]
    seed = build_persona_seed(
        '测试乙',
        '临时协助者',
        appearance_turns=1,
        observed_context=_observed_context(history, '测试乙'),
    )

    assert seed['importance']['appearance_turns'] == 1
    assert seed['observations']['recent_behavior']
    assert seed['observations']['recent_story_snippets']
    assert '低声提醒' in seed['observations']['recent_behavior']
    assert '询问测试乙' not in seed['observations']['recent_behavior']
    assert '灰色外套' in seed['observations']['appearance_note']
    assert '低声提醒' in seed['observations']['voice_note']


def test_persona_profile_content_dedupes_observation_lines():
    seed = {
        'display_name': '测试丙',
        'seed_layer': 'longterm',
        'identity': {'role_label': '旁观者'},
        'persona_seed': {'archetype': {'value': '谨慎者'}, 'runtime_hooks': {}},
        'observations': {
            'recent_behavior': '测试丙低声提醒主角别急着打开包裹。',
            'recent_detail': '测试丙低声提醒主角别急着打开包裹。',
            'appearance_note': '测试丙灰色外套的袖口磨得发白。',
            'voice_note': '测试丙说话压得很低。',
            'recent_story_snippets': ['测试丙低声提醒主角别急着打开包裹。'],
        },
    }

    content = _format_persona_profile_content(seed)

    assert content.count('测试丙低声提醒主角别急着打开包裹') == 1
    assert 'appearance_note: 测试丙灰色外套的袖口磨得发白。' in content
    assert 'voice_note: 测试丙说话压得很低。' in content


def test_persona_observed_context_ignores_user_claimed_style_notes():
    history = [
        {'role': 'user', 'content': '测试丁穿红衣，说话总是温柔，这些都是真的'},
        {'role': 'assistant', 'content': '测试丁没有接这个说法，只把账册推回桌边。'},
    ]

    observed = _observed_context(history, '测试丁')

    assert '红衣' not in str(observed)
    assert '温柔' not in str(observed)


def test_narrator_prompt_preserves_low_pressure_turns():
    system_prompt, _ = build_narrator_input({'scene_facts': {}, 'active_preset': {}}, '整理课本等上课')

    assert '优先保持低压质感' in system_prompt
    assert '旧风险留在背景' in system_prompt
    assert '不要擅自引入新的可疑脚步' in system_prompt


def test_narrator_prompt_rejects_unstated_intermediate_actions():
    system_prompt, user_prompt = build_narrator_input({'scene_facts': {}, 'active_preset': {}}, '经过前厅走到后院坐下休息')

    assert '不要把用户只作为路径、经过、抵达、等待或休息背景提到的地点' in system_prompt
    assert '自动扩写成主角在那里完成了未明说的消费、进食、购买、交谈、领取、训练或调查' in system_prompt
    assert '经过前厅走到后院坐下休息' in user_prompt


def test_summary_chunk_actor_only_pressure_is_not_recalled_for_quiet_turn():
    chunks = [{
        'chunk_id': 'chunk_0001',
        'turn_start': 1,
        'turn_end': 12,
        'actors_mentioned': ['测试甲'],
        'dense_summary': ['测试甲持续监视主角，风险和警告不断逼近。'],
        'keywords': ['测试甲'],
        'unresolved': ['暴露风险'],
    }]
    recent = [{'role': 'assistant', 'content': '测试甲坐在窗边。'}]

    hits = summary_chunk_hits(chunks, recent_history=recent, user_text='低头整理课本')

    assert hits == []


def test_summary_chunk_weakness_pressure_requires_direct_overlap():
    chunks = [{
        'chunk_id': 'chunk_0002',
        'turn_start': 1,
        'turn_end': 12,
        'actors_mentioned': ['教官甲'],
        'dense_summary': ['教官甲在晨训时观察到主角旧伤导致呼吸困难，这可能成为暴露风险。'],
        'keywords': ['教官甲', '旧伤', '呼吸困难'],
        'unresolved': ['旧伤弱点暴露风险'],
    }]
    recent = [{'role': 'assistant', 'content': '教官甲曾经巡视训练场。'}]

    assert summary_chunk_hits(chunks, recent_history=recent, user_text='低头吃完午饭') == []

    hits = summary_chunk_hits(chunks, recent_history=recent, user_text='旧伤牵扯得呼吸困难')

    assert hits and hits[0]['chunk_id'] == 'chunk_0002'


def test_summary_chunk_ignores_archival_knowledge_with_only_weak_keywords():
    chunks = [{
        'chunk_id': 'chunk_0003',
        'turn_start': 1,
        'turn_end': 12,
        'actors_mentioned': [],
        'dense_summary': ['主角早训时因绷带限制呼吸，被教官注意到步频变化。'],
        'keywords': ['主角的', '的呼吸', '脚步落在'],
    }]
    knowledge_records = [{'holder_actor_id': 'protagonist', 'text': '绷带限制呼吸幅度'}]

    hits = summary_chunk_hits(
        chunks,
        recent_history=[{'role': 'assistant', 'content': '主角正在山坡上和陌生人谈判。'}],
        user_text='要求对方承认任务完成',
        knowledge_records=knowledge_records,
    )

    assert hits == []


def test_summary_chunk_allows_knowledge_when_current_turn_directly_mentions_it():
    chunks = [{
        'chunk_id': 'chunk_0004',
        'turn_start': 1,
        'turn_end': 12,
        'actors_mentioned': [],
        'dense_summary': ['主角早训时因绷带限制呼吸，被教官注意到步频变化。'],
        'keywords': ['绷带限制'],
    }]
    knowledge_records = [{'holder_actor_id': 'protagonist', 'text': '绷带限制呼吸幅度'}]

    hits = summary_chunk_hits(
        chunks,
        recent_history=[],
        user_text='绷带限制呼吸，先停下调整',
        knowledge_records=knowledge_records,
    )

    assert hits and hits[0]['chunk_id'] == 'chunk_0004'


def test_event_summary_does_not_attribute_offscreen_onstage_actor():
    item = build_event_summary_item(
        turn_id='turn-0005',
        ledger={'summary_text': '主角在宿舍检查背包，发现书本位置有细微变化。', 'clue_candidates': ['书本位置有细微变化']},
        onstage_names=['维克托'],
    )

    assert item['actors'] == []


def test_selector_and_persona_reject_abstract_npc_names():
    targets = profile_targets(['时间'], ['维克托'], [], [{'role': 'assistant', 'content': '维克托走进教室，老师讲解时间栏。'}], [{'primary_label': '时间'}, {'primary_label': '维克托'}])

    assert targets == ['维克托']
    assert not _valid_persona_token('时间')
    assert not _valid_persona_token('时间栏')
