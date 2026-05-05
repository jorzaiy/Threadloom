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
            'weaknesses': ['束胸导致剧烈运动时呼吸困难'],
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
    assert '束胸导致剧烈运动时呼吸困难' in system_prompt
    assert '不被发现真实身份' in system_prompt
