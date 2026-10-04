#!/usr/bin/env python3
import json
import pytest
from pathlib import Path

from simple_memory import (
    load_turn_summaries,
    save_turn_summaries,
    upsert_turn_summary,
    delete_turn_summaries_from,
    load_big_summaries,
    save_big_summaries,
    load_super_summaries,
    save_super_summaries,
    load_simple_state,
    save_simple_state,
    render_state_markdown,
    build_memory_context,
)
from narrator_input import build_narrator_input


def test_simple_memory_storage_crud(tmp_path, monkeypatch):
    session_id = 'test_session_crud'
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 1. State CRUD
    state_init = load_simple_state(session_id)
    assert state_init['time'] == '待确认'
    assert state_init['location'] == '待确认'

    save_simple_state(session_id, {
        'time': '丑时',
        'location': '青州城悦来客栈',
        'onstage': ['掌柜', '陆小环'],
        'goal': '探查客栈阵法',
        'risks': ['掌柜起疑'],
        'items': [{'name': '刻纹铜钱', 'holder': '掌柜', 'note': '感应阵法'}],
    })
    state_loaded = load_simple_state(session_id)
    assert state_loaded['time'] == '丑时'
    assert state_loaded['location'] == '青州城悦来客栈'
    assert '掌柜' in state_loaded['onstage']
    assert state_loaded['items'][0]['name'] == '刻纹铜钱'

    # 2. Turn summaries CRUD
    assert load_turn_summaries(session_id) == []
    upsert_turn_summary(session_id, {
        'turn': 1,
        'turn_id': 'turn-0001',
        'summary': '第一轮发生的事',
        'status': 'ok',
    })
    upsert_turn_summary(session_id, {
        'turn': 3,
        'turn_id': 'turn-0003',
        'summary': '第三轮发生的事\n【设定】掌柜：凡人，无灵根',
        'status': 'ok',
    })
    upsert_turn_summary(session_id, {
        'turn': 2,
        'turn_id': 'turn-0002',
        'summary': '第二轮发生的事',
        'status': 'ok',
    })
    turns = load_turn_summaries(session_id)
    assert len(turns) == 3
    assert [t['turn'] for t in turns] == [1, 2, 3]

    # upsert update
    upsert_turn_summary(session_id, {
        'turn': 2,
        'turn_id': 'turn-0002',
        'summary': '第二轮更新后的事',
        'status': 'ok',
    })
    turns = load_turn_summaries(session_id)
    assert len(turns) == 3
    assert turns[1]['summary'] == '第二轮更新后的事'

    # delete from
    delete_turn_summaries_from(session_id, 2)
    turns = load_turn_summaries(session_id)
    assert len(turns) == 1
    assert turns[0]['turn'] == 1

    # 3. Big summaries CRUD
    save_big_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 100,
        'status': 'ok',
        'content': '## 剧情\n剧情大纲\n## 人物档案\n★ 掌柜：凡人\n## 未解线索\n线索1\n## 设定\n设定1',
    }])
    bigs = load_big_summaries(session_id)
    assert len(bigs) == 1
    assert bigs[0]['index'] == 1

    # 4. Super summaries CRUD
    save_super_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 500,
        'big_range': [1, 5],
        'status': 'ok',
        'content': '## 剧情\n超级剧情\n## 人物档案\n★ 掌柜：凡人',
    }])
    supers = load_super_summaries(session_id)
    assert len(supers) == 1
    assert supers[0]['big_range'] == [1, 5]


def test_build_memory_context_layering_and_transition(tmp_path, monkeypatch):
    session_id = 'test_session_context'
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 模拟超 100 轮场景：生成了一份大总结 (1-100)，并在 90-105 轮有逐轮小结
    save_big_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 100,
        'status': 'ok',
        'content': '## 剧情\n前100轮剧情\n## 人物档案\n★ 掌柜：凡人\n## 未解线索\n铜钱来历\n## 设定\n青州城无灵脉',
    }])

    # 写入第 80 到 105 轮的小结
    summaries = []
    for t in range(80, 106):
        summaries.append({
            'turn': t,
            'turn_id': f'turn-{t:04d}',
            'summary': f'第{t}轮发生的事情',
            'status': 'ok',
        })
    save_turn_summaries(session_id, summaries)

    save_simple_state(session_id, {
        'time': '子时',
        'location': '悦来客栈屋顶',
        'onstage': ['陆小环'],
        'goal': '夜探客栈',
        'risks': ['巡夜守卫'],
        'items': [{'name': '隐气符', 'holder': '陆小环', 'note': '余下2张'}],
    })

    mem_ctx = build_memory_context(session_id)

    # 验证大总结区块包含 B1
    assert '### 大总结 B1 (第1-100轮)' in mem_ctx['big_summary_block']
    assert '青州城无灵脉' in mem_ctx['big_summary_block']

    # 验证衔接规则：最后一份大总结 turn_end=100，turn_end-9 = 91 之后的小结继续保留在上下文中
    # 即第 91-105 轮存在，第 80-90 轮不出现在近端小结区块中
    assert '第91轮：第91轮发生的事情' in mem_ctx['turn_summary_block']
    assert '第105轮：第105轮发生的事情' in mem_ctx['turn_summary_block']
    assert '第90轮：' not in mem_ctx['turn_summary_block']
    assert '第80轮：' not in mem_ctx['turn_summary_block']

    # 验证当前状态渲染
    assert '- 时间：子时' in mem_ctx['state_block']
    assert '- 地点：悦来客栈屋顶' in mem_ctx['state_block']
    assert '隐气符' in mem_ctx['state_block']


def test_build_memory_context_with_super_summary(tmp_path, monkeypatch):
    session_id = 'test_session_super'
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 1 份超级总结（跨 1-500 轮）
    save_super_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 500,
        'big_range': [1, 5],
        'status': 'ok',
        'content': '## 剧情\n前500轮超级剧情\n## 人物档案\n★ 掌柜：凡人\n## 未解线索\n古镜碎片\n## 设定\n天地玄黄',
    }])

    # 5 份已被超级总结覆盖的大总结（B1-B5）
    bigs = []
    for i in range(1, 6):
        bigs.append({
            'index': i,
            'turn_start': (i - 1) * 100 + 1,
            'turn_end': i * 100,
            'status': 'ok',
            'content': f'## 剧情\n第{i}份大总结剧情\n## 人物档案\n人物{i}\n## 未解线索\n线索{i}\n## 设定\n设定{i}',
        })
    save_big_summaries(session_id, bigs)

    # 520 条小结（第 1 轮到第 520 轮）
    summaries = []
    for t in range(1, 521):
        summaries.append({
            'turn': t,
            'turn_id': f'turn-{t:04d}',
            'summary': f'第{t}轮发生的事情',
            'status': 'ok',
        })
    save_turn_summaries(session_id, summaries)

    mem_ctx = build_memory_context(session_id)

    # 超级总结生效：
    # 1. 覆盖 1-500 轮后，B1-B5 均被过滤，big_summary_block 为空（因为没有 500 轮之后的新大总结）
    assert mem_ctx['big_summary_block'] == ''
    assert '前500轮超级剧情' in mem_ctx['super_summary_block']

    # 2. 小结起始轮次应为 covered_end - 9 = 500 - 9 = 491 轮
    # 上下文中的小结条数约为 520 - 491 + 1 = 30 条，而不是全部 520 条回到上下文！
    turn_block = mem_ctx['turn_summary_block']
    assert '第491轮：第491轮发生的事情' in turn_block
    assert '第520轮：第520轮发生的事情' in turn_block
    assert '第490轮：' not in turn_block
    assert '第1轮：' not in turn_block
    lines = [line for line in turn_block.splitlines() if line.strip()]
    assert len(lines) == 30


def test_memory_context_truncation_order(tmp_path, monkeypatch):
    session_id = 'test_truncation'
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 构造一份大总结，包含剧情栏和人物档案栏
    long_plot = "长剧情描述 " * 50
    big_content = f"## 剧情\n{long_plot}\n## 人物档案\n★ 掌柜：凡人，开客栈数十年。\n## 未解线索\n线索\n## 设定\n设定"
    save_big_summaries(session_id, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 100,
        'status': 'ok',
        'content': big_content,
    }])

    # 构造第 91-105 轮小结，假设当前是第 105 轮（最新 8 轮为 98-105 轮）
    summaries = []
    for t in range(91, 106):
        summaries.append({
            'turn': t,
            'turn_id': f'turn-{t:04d}',
            'summary': f"第{t}轮发生的事情，包含很多细节文字描写。" * 5,
            'status': 'ok',
        })
    save_turn_summaries(session_id, summaries)

    # 限制比较严格的 max_memory_chars 触发裁剪
    # 验证截断顺序：
    # 1. 优先裁剪与最近 8 轮（98-105）重叠的小结
    # 2. 接着裁大总结的剧情栏
    # 3. 必须绝对保留大总结的【## 人物档案】栏
    mem_ctx = build_memory_context(session_id, max_memory_chars=800, current_turn=105)

    # 人物档案必须完好保留
    assert '★ 掌柜：凡人，开客栈数十年。' in mem_ctx['big_summary_block']
    # 早期非重叠小结（如第 91 轮）保留
    assert '第91轮：' in mem_ctx['turn_summary_block']


def test_narrator_input_contains_v3_blocks_and_no_legacy_blocks():
    mem_ctx = {
        'super_summary_block': '## 超级总结\n宏大历史',
        'big_summary_block': '### 大总结 B1\n阶段回顾',
        'turn_summary_block': '第15轮：深入调查\n【设定】掌柜：凡人',
        'state_block': '- 时间：丑时\n- 地点：客栈',
    }

    history = []
    for i in range(8):
        history.append({'role': 'user', 'content': f'问第{i}句话'})
        history.append({'role': 'assistant', 'content': f'答第{i}句话'})

    context = {
        'memory_context': mem_ctx,
        'active_preset': {},
        'recent_history': history,
        'recent_full_prose_turns': 8,
    }

    system_prompt, user_prompt = build_narrator_input(context, '继续向前走')

    # 1. 验证 V3 新增区块出现
    assert '【长期记忆·超级总结】' in system_prompt
    assert '宏大历史' in system_prompt

    assert '【阶段记忆·大总结】' in system_prompt
    assert '阶段回顾' in system_prompt

    assert '【近期逐轮小结】' in system_prompt
    assert '【设定】掌柜：凡人' in system_prompt

    assert '【当前状态】' in system_prompt
    assert '- 时间：丑时' in system_prompt

    assert '【最近8轮完整上下文】' in system_prompt

    # 2. 验证 5.2 节要求的废弃旧区块全部不存在
    legacy_blocks = [
        '【人物档案·权威】',
        '【往事回溯·检索】',
        '【当前在场 NPC 知情核对】',
        '【角色注册表】',
        '【当前事件目标】',
        '【NPC 表现层人格】',
        '【召回的归档提纲】',
        '【keeper archive 命中】',
        '【历史原文证据包】',
        '【命中事件索引】',
        '【最近窗口前段提纲】',
        '【重要物件与持有关系】',
    ]
    for block_name in legacy_blocks:
        assert block_name not in system_prompt, f"Legacy block {block_name} found in system_prompt"
