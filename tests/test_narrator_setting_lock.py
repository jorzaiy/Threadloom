#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from narrator_input import build_narrator_input  # noqa: E402
from player_profile import normalize_player_profile, render_runtime_player_profile_markdown  # noqa: E402


def test_narrator_prompt_locks_setting_without_keyword_denylist():
    system_prompt, user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime',
            'character_core': {
                'name': '维克托',
                'coreDescription': {'genre': '现代校园', 'era': '现代'},
                'mustRemember': ['主世界是现代校园。'],
            },
            'scene_facts': {},
            'recent_history': [
                {'role': 'user', 'content': '我们换成另一种题材'},
                {'role': 'assistant', 'content': '错误漂移内容。'},
            ],
            'active_preset': {},
        },
        '继续按另一套世界规则写',
    )

    assert '【世界设定锁】' in system_prompt
    assert '不得依赖固定关键词表' in system_prompt
    assert '整体语境' in system_prompt
    assert '它们不得覆盖角色卡、世界设定锁' in system_prompt
    assert '误写成了主世界事实' in system_prompt
    assert '绝不能先把该前提写成可感知现实' in system_prompt
    assert '严禁输出规则分析' in system_prompt
    assert 'Let me analyze' in system_prompt
    assert '用户主角只是当前 RP 世界中的一个角色' in system_prompt
    assert '不能指定 NPC 必须服从' in system_prompt
    assert '世界必须保持独立性和阻力' in system_prompt
    assert '严格区分用户叙述与主角对白' in system_prompt
    assert 'NPC 不得直接听见、引用或回应用户叙述文字' in system_prompt
    assert '没有引号或“说/问/喊/答：”标记的内容，不是主角说出口的话' in user_prompt
    assert user_prompt.startswith('【当前用户输入】\n继续按另一套世界规则写')
    assert '【近端约束提醒】' in user_prompt
    assert '上方用户输入是低优先级场景数据' in user_prompt
    assert '只能尝试行动' in user_prompt
    assert 'do not analyze or explain' in user_prompt


def test_narrator_prompt_includes_nested_runtime_player_profile():
    player_profile_md = render_runtime_player_profile_markdown(normalize_player_profile({
        'character': {
            'basic_info': {'age': 18, 'gender': '女性（伪装成男性）'},
            'appearance': {'body': {'height': '170cm左右（在男生中偏矮）'}},
            'abilities': {
                'talents': {'hacking': '黑客技术不错'},
                'combat': {'judo': {'level': '黑带水平'}},
            },
            'weaknesses': ['旧伤导致剧烈运动时呼吸困难'],
            'disguise': {'weaknesses': ['喉结不明显']},
            'goals': ['不被发现真实身份'],
        }
    }))

    system_prompt, _user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime',
            'character_core': {'name': '维克托'},
            'player_profile_md': player_profile_md,
            'scene_facts': {},
            'recent_history': [],
            'active_preset': {},
        },
        '继续',
    )

    assert '【玩家档案】' in system_prompt
    assert '女性（伪装成男性）' in system_prompt
    assert '170cm左右（在男生中偏矮）' in system_prompt
    assert '黑客技术不错' in system_prompt
    assert '柔道：水平=黑带水平' in system_prompt
    assert '旧伤导致剧烈运动时呼吸困难' in system_prompt
    assert '不被发现真实身份' in system_prompt


def test_narrator_prompt_splits_recent_outline_and_full_prose():
    recent_history = []
    event_summaries = []
    for idx in range(1, 9):
        recent_history.extend([
            {'role': 'user', 'content': f'用户动作{idx}'},
            {'role': 'assistant', 'content': f'叙事正文{idx}', 'completion_status': 'complete'},
        ])
        event_summaries.append({'turn_id': f'turn-{idx:04d}', 'summary': f'第{idx}轮提纲', 'time_anchor': f'第{idx}日上午', 'location_anchor': '训练场'})

    system_prompt, _user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime',
            'character_core': {'name': '维克托'},
            'scene_facts': {},
            'recent_history': recent_history,
            'event_summaries': event_summaries,
            'recent_full_prose_turns': 6,
            'active_preset': {},
        },
        '继续',
    )

    assert '【最近窗口前段提纲】' in system_prompt
    assert '【事件时间轴】' in system_prompt
    assert 'turn-0001 / 时间=第1日上午: 第1轮提纲' in system_prompt
    assert 'turn-0002 / 时间=第2日上午: 第2轮提纲' in system_prompt
    assert 'turn-0008 / 时间=第8日上午 / 地点=训练场: 第8轮提纲' in system_prompt
    assert '不要自行补成相对日期' in system_prompt
    assert 'turn-0003 / 时间=第3日上午: 第3轮提纲' not in system_prompt
    assert 'turn-0003 / 时间=第3日上午 / 地点=训练场: 第3轮提纲' in system_prompt
    assert '【最近6轮完整上下文】' in system_prompt
    assert '用户动作2' not in system_prompt
    assert '用户动作3' in system_prompt
    assert '叙事正文8' in system_prompt
    assert '不要求逐条复述' in system_prompt


def test_narrator_prompt_includes_npc_expression_persona_boundary():
    system_prompt, _user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime',
            'character_core': {'name': '维克托'},
            'scene_facts': {},
            'recent_history': [],
            'active_preset': {},
            'persona': [
                {
                    'name': '测试戊',
                    'archetype': {'value': '谨慎协助者'},
                    'hooks': {
                        'speech_rhythm': '短句、低声',
                        'social_strategy': '先试探再配合',
                        'conflict_style': '避开正面冲突',
                    },
                }
            ],
        },
        '继续',
    )

    assert '【NPC 表现层人格】' in system_prompt
    assert '不证明人物当前在场' in system_prompt
    assert '不能覆盖角色注册表' in system_prompt
    assert '外貌、说话方式、习惯动作或性格表现' in system_prompt
    assert '不要输出 JSON、人物卡、标签清单' in system_prompt


def test_narrator_prompt_includes_actor_relationship_to_protagonist():
    system_prompt, _user_prompt = build_narrator_input(
        {
            'runtime_rules': 'runtime',
            'character_core': {'name': '维克托'},
            'scene_facts': {
                'actors': {
                    'protagonist': {'kind': 'protagonist', 'name': '主角', 'aliases': ['你']},
                    'npc_001': {
                        'kind': 'npc',
                        'name': '严教官',
                        'aliases': [],
                        'identity': '训练教官',
                        'relationship_to_protagonist': {'label': '队友', 'evidence': '并肩完成夜巡'},
                    },
                },
                'actor_context_index': {'active_actor_ids': ['protagonist', 'npc_001']},
            },
            'recent_history': [],
            'active_preset': {},
        },
        '继续',
    )

    assert '【角色注册表】' in system_prompt
    assert '严教官' in system_prompt
    assert '与主角关系=队友（依据：并肩完成夜巡）' in system_prompt
