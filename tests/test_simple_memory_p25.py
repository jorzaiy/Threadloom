#!/usr/bin/env python3
"""
P2.5 验收测试用例：
1. 构造场景：主角独自调包了活物，掌柜随后去探查阵法。
   - 状态里有对应的秘密，misbelief 中记录了掌柜；
   - 叙述 prompt 的【当前状态】里，能看到按人展开的秘密内容。
2. 构造一段主角不在场、NPC 之间密谋的叙述原文，确认生成的小结和 secrets 中，主角都不在知情者里。
3. 用假模型输出 12 条秘密，确认代码最终只保留 8 条，被挤出的条目写进了【知情】行。
4. 大总结 prompt 和超级总结 prompt 都包含 ## 秘密与知情 栏，并且 ★ 人物相关的秘密不会被删除。
"""
import json
import pytest
from pathlib import Path

from simple_memory import (
    build_memory_context,
    fill_prompt_template,
    generate_big_summary,
    generate_super_summary,
    generate_turn_summary,
    load_simple_state,
    render_state_markdown,
    save_big_summaries,
    save_simple_state,
    save_super_summaries,
    verify_and_restore_stars,
)
from narrator_input import build_narrator_input


SESSION_P25 = 'p25_acceptance_session'


def test_p25_secret_structure_and_render_expansion(tmp_path, monkeypatch):
    """验收点 1：状态记录 secrets，且 prompt 【当前状态】中按人展开。"""
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    secret_item = {
        'content': '阵中活物已被陆小环调包，藏进储物袋',
        'owner': '陆小环',
        'knowers': ['陆小环'],
        'misbelief': {'掌柜': '以为活物仍封在阵中'},
        'suspects': {'青衫年轻人': '知道隔壁有人动过阵，不知道结果'},
    }

    save_simple_state(SESSION_P25, {
        'time': '丑时',
        'location': '悦来客栈天字三号房',
        'onstage': ['陆小环'],
        'goal': '调包活物并潜伏',
        'risks': ['掌柜随时查看大阵'],
        'items': [{'name': '储物袋', 'holder': '陆小环', 'note': '内有活物'}],
        'secrets': [secret_item],
    })

    state = load_simple_state(SESSION_P25)
    assert len(state['secrets']) == 1
    assert state['secrets'][0]['misbelief']['掌柜'] == '以为活物仍封在阵中'

    # 验证 render_state_markdown 展开格式
    rendered = render_state_markdown(state)
    assert '- 秘密与知情：' in rendered
    assert '阵中活物已被陆小环调包，藏进储物袋' in rendered
    assert '知情：陆小环' in rendered
    assert '误以为：掌柜（以为活物仍封在阵中）' in rendered
    assert '有所察觉：青衫年轻人（知道隔壁有人动过阵，不知道结果）' in rendered

    # 验证注入到叙述 prompt
    mem_ctx = build_memory_context(SESSION_P25)
    sys_prompt, _ = build_narrator_input({'memory_context': mem_ctx, 'active_preset': {}}, '查看门外动静')
    assert '【知情边界】' in sys_prompt
    assert 'NPC 只能知道这三类内容' in sys_prompt
    assert '【当前状态】' in sys_prompt
    assert '误以为：掌柜（以为活物仍封在阵中）' in sys_prompt


def test_p25_npc_only_conspiracy_excludes_protagonist(tmp_path, monkeypatch):
    """验收点 2：主角不在场的 NPC 密谋，小结和 secrets 中主角均不在知情人列表中。"""
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    mock_history = {
        'turn_index': 1,
        'turn_id': 'turn-0001',
        'user': {'role': 'user', 'content': '（在天字三号房内闭目调息）'},
        'assistant': {'role': 'assistant', 'content': '客栈后厨地窖内，掌柜向青衫年轻人低声道：今夜拍卖会后，按老规矩把阵中截获的灵兽送去万宝商会。年轻人颔首应允。'},
    }
    monkeypatch.setattr('simple_memory.load_history_turn_pair', lambda _sid, _t: mock_history)

    # 模拟 summarizer 输出
    model_response = {
        'summary': '后厨地窖内，掌柜与青衫年轻人密谋在拍卖会后移交阵中灵兽。\n【知情】掌柜与青衫年轻人：商定拍卖会后将灵兽转交万宝商会',
        'state': {
            'time': '丑时',
            'location': '悦来客栈后厨地窖',
            'onstage': ['掌柜', '青衫年轻人'],
            'goal': '密谋移交灵兽',
            'risks': [],
            'items': [],
            'secrets': [
                {
                    'content': '掌柜与青衫年轻人密谋在拍卖会后把灵兽送去万宝商会',
                    'owner': '掌柜',
                    'knowers': ['掌柜', '青衫年轻人'],
                    'misbelief': {},
                    'suspects': {},
                }
            ],
        },
    }
    monkeypatch.setattr('simple_memory.call_model', lambda cfg, sys, usr: (json.dumps(model_response, ensure_ascii=False), {'model': 'fake'}))
    monkeypatch.setattr('simple_memory.resolve_provider_model', lambda role: {'model': 'fake'})

    result = generate_turn_summary(SESSION_P25, 1)
    sec = result['state_after']['secrets'][0]
    assert '陆小环' not in sec['knowers']
    assert '主角' not in sec['knowers']
    assert set(sec['knowers']) == {'掌柜', '青衫年轻人'}
    assert '陆小环' not in result['summary']


def test_p25_secret_limit_8_and_overflow_to_knowledge_line(tmp_path, monkeypatch):
    """验收点 3：输出 12 条秘密，最终只保留 8 条，被挤出的 4 条追加进小结【知情】行。"""
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    mock_history = {
        'turn_index': 5,
        'turn_id': 'turn-0005',
        'user': {'role': 'user', 'content': '打探消息'},
        'assistant': {'role': 'assistant', 'content': '打探到了诸多消息。'},
    }
    monkeypatch.setattr('simple_memory.load_history_turn_pair', lambda _sid, _t: mock_history)

    twelve_secrets = [
        {
            'content': f'秘密第{i}号',
            'owner': f'人物{i}',
            'knowers': [f'人物{i}'],
            'misbelief': {},
            'suspects': {},
        }
        for i in range(1, 13)
    ]

    model_response = {
        'summary': '主角探听到各种秘密消息。',
        'state': {
            'time': '丑时',
            'location': '茶馆',
            'onstage': [],
            'goal': '收集情报',
            'risks': [],
            'items': [],
            'secrets': twelve_secrets,
        },
    }
    monkeypatch.setattr('simple_memory.call_model', lambda cfg, sys, usr: (json.dumps(model_response, ensure_ascii=False), {'model': 'fake'}))
    monkeypatch.setattr('simple_memory.resolve_provider_model', lambda role: {'model': 'fake'})

    result = generate_turn_summary(SESSION_P25, 5)

    # 1. state.secrets 仅保留最近的 8 条（第 5 到 12 号）
    retained_secrets = result['state_after']['secrets']
    assert len(retained_secrets) == 8
    assert retained_secrets[0]['content'] == '秘密第5号'
    assert retained_secrets[-1]['content'] == '秘密第12号'

    # 2. 被挤出的 1~4 号写入小结的【知情】行
    summary = result['summary']
    assert '【知情】（归档）秘密第1号' in summary
    assert '【知情】（归档）秘密第2号' in summary
    assert '【知情】（归档）秘密第3号' in summary
    assert '【知情】（归档）秘密第4号' in summary


def test_p25_big_and_super_summary_prompts_and_star_secret_preservation():
    """验收点 4：大总结和超级总结包含 ## 秘密与知情，且 ★ 角色相关的秘密不被删除。"""
    big_prompt = Path('prompts/memory/big-summary.md').read_text(encoding='utf-8')
    assert '## 秘密与知情' in big_prompt
    assert '与带 ★ 角色相关的秘密和伪装，绝对不得删除' in big_prompt

    super_prompt = Path('prompts/memory/super-summary.md').read_text(encoding='utf-8')
    assert '## 秘密与知情' in super_prompt
    assert '与带 ★ 角色相关的秘密和伪装，绝对不得删除' in super_prompt

    # 验证 verify_and_restore_stars 能保护 ★ 角色丢失的秘密
    prev_big = """
## 剧情
剧情。

## 人物档案
★ 掌柜：凡人，客栈掌柜。

## 未解线索
无

## 设定
无

## 秘密与知情
- 掌柜私下隐瞒铜钱与大阵连接（知情：掌柜）
"""
    new_model_output = """
## 剧情
新剧情。

## 人物档案
小二：跑堂。

## 未解线索
无

## 设定
无

## 秘密与知情
- 无其他重要秘密
"""
    restored_content, restored_names = verify_and_restore_stars(new_model_output, prev_big)
    assert '掌柜' in restored_names
    assert '★ 掌柜：凡人' in restored_content
    # ★ 角色关联的秘密被原样恢复在“## 秘密与知情”栏中
    assert '掌柜私下隐瞒铜钱与大阵连接' in restored_content
