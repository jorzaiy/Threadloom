
#!/usr/bin/env python3
import json
import pytest
from pathlib import Path

from simple_memory import (
    build_memory_context,
    load_turn_summaries,
    save_big_summaries,
    save_turn_summaries,
    upsert_turn_summary,
    verify_and_restore_stars,
)
from narrator_input import build_narrator_input


def test_star_preservation_and_auto_restore():
    prev_big = """
## 剧情
前序剧情。

## 人物档案
★ 掌柜：凡人，开客栈三十年，知晓阵法铜钱。
小二：青年，勤勉。

## 未解线索
无

## 设定
无
"""
    # 模拟模型在总结中丢掉了 ★ 掌柜
    new_model_output = """
## 剧情
后续新剧情推进。

## 人物档案
小二：青年。

## 未解线索
无

## 设定
无
"""
    from simple_memory import verify_and_restore_stars
    restored_content, restored_names = verify_and_restore_stars(new_model_output, prev_big)
    assert '掌柜' in restored_names
    assert '★ 掌柜：凡人，开客栈三十年，知晓阵法铜钱。' in restored_content


def test_zhanggui_regression_case(tmp_path, monkeypatch):
    """
    12 节关键回归用例：
    玩家在第 3 轮纠正'掌柜只是凡人'，之后持续多轮。
    1. 第 3 轮小结必须有【设定】掌柜：凡人
    2. 之后每一轮叙述 prompt 里都能找到这条设定
    3. 大总结里掌柜仍然是凡人，且全程不出现'客栈掌门'
    """
    session_id = 'test_zhanggui_session'
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 写入第 1~2 轮小结
    upsert_turn_summary(session_id, {
        'turn': 1,
        'turn_id': 'turn-0001',
        'summary': '主角来到青州城悦来客栈住下。',
        'status': 'ok',
    })
    upsert_turn_summary(session_id, {
        'turn': 2,
        'turn_id': 'turn-0002',
        'summary': '主角在客栈向掌柜打听城中异动。',
        'status': 'ok',
    })

    # 第 3 轮：玩家输入纠正
    upsert_turn_summary(session_id, {
        'turn': 3,
        'turn_id': 'turn-0003',
        'summary': '主角试探掌柜经脉，确认其没有半点修为。\n【设定】玩家纠正：掌柜只是凡人，无灵根，靠祖传铜钱感应阵法。',
        'status': 'ok',
    })

    # 模拟对话持续到第 25 轮
    for t in range(4, 26):
        upsert_turn_summary(session_id, {
            'turn': t,
            'turn_id': f'turn-{t:04d}',
            'summary': f'第{t}轮发生的事情。',
            'status': 'ok',
        })

    # 验证每一轮构建上下文时，第 3 轮的小结与【设定】均在 prompt 中可见
    for current_t in range(4, 26):
        mem_ctx = build_memory_context(session_id, current_turn=current_t)
        sys_prompt, _ = build_narrator_input(
            {
                'memory_context': mem_ctx,
                'active_preset': {},
                'recent_history': [{'role': 'user', 'content': '行动'}, {'role': 'assistant', 'content': '结果'}],
                'recent_full_prose_turns': 8,
            },
            '继续调查',
        )
        assert '【设定】玩家纠正：掌柜只是凡人' in sys_prompt
        assert '客栈掌门' not in sys_prompt

    # 模拟生成大总结
    big_summary_content = """
## 剧情
主角在客栈落脚，暗中排查客栈大阵与各方势力。

## 人物档案
★ 掌柜：凡人，客栈掌柜，无灵根修为，靠刻纹铜钱感应阵法。对主角客气谨慎。

## 未解线索
铜钱来源（第3轮前后）。

## 设定
悦来客栈暗藏感应阵法。
"""
    save_big_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 100,
        'status': 'ok',
        'content': big_summary_content,
    }])

    # 验证大总结生成后，掌柜依然是凡人且无“客栈掌门”
    mem_ctx = build_memory_context(session_id, current_turn=101)
    sys_prompt, _ = build_narrator_input(
        {
            'memory_context': mem_ctx,
            'active_preset': {},
            'recent_history': [],
            'recent_full_prose_turns': 8,
        },
        '下楼',
    )
    assert '★ 掌柜：凡人' in sys_prompt
    assert '客栈掌门' not in sys_prompt
