#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from narrator_input import build_narrator_input  # noqa: E402


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
    assert user_prompt == '【当前用户输入】\n继续按另一套世界规则写'
