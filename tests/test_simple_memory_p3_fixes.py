#!/usr/bin/env python3
import json
import pytest
from pathlib import Path

from simple_memory import (
    build_memory_context,
    load_big_summaries,
    load_simple_state,
    load_super_summaries,
    load_turn_summaries,
    save_big_summaries,
    save_simple_state,
    save_super_summaries,
    save_turn_summaries,
    upsert_turn_summary,
)
import server
from tests.test_simple_memory_p3 import p3_env, DummyHandler, SESSION_P3


def test_edited_state_persists_to_next_turn_summary(p3_env, monkeypatch):
    """
    验收测试 1：面板上手动修改状态后，下一轮小结生成时能继承到手动修改的值，不会被覆盖。
    """
    # 模拟第 1 轮已经有小结，此时其 state_after 是地点：青州城
    turns = load_turn_summaries(SESSION_P3)
    assert len(turns) == 1
    turns[0]['state_after'] = {'time': '午时', 'location': '青州城', 'goal': '打探消息'}
    save_turn_summaries(SESSION_P3, turns)

    # 玩家在面板中手动编辑状态为：地点=黑风山，目标=暗杀首领
    h = DummyHandler()
    h._post_memory_state(None, {
        'session_id': SESSION_P3,
        'state': {
            'time': '子时',
            'location': '黑风山',
            'goal': '暗杀首领',
            'onstage': ['陆小环'],
            'risks': ['岗哨发现'],
            'items': [],
            'secrets': [],
        },
    })
    assert h.response_status == 200

    # 验证第一轮小结的 state_after 也被同步更新
    turns = load_turn_summaries(SESSION_P3)
    assert turns[0]['state_after']['location'] == '黑风山'
    assert turns[0]['state_after']['goal'] == '暗杀首领'

    # 现在模拟生成第 2 轮小结，拦截 call_model 查看传入的 previous_state
    captured_previous_state = {}

    def fake_call(cfg, sys_prompt, user_prompt):
        nonlocal captured_previous_state
        # user_prompt 包含 previous_state
        for line in user_prompt.splitlines():
            if '"location": "黑风山"' in line or '"goal": "暗杀首领"' in line:
                captured_previous_state['found'] = True
        return json.dumps({
            'summary': '第2轮行动继续',
            'state': {'location': '黑风山山寨大厅'},
        }), {'model': 'fake'}

    monkeypatch.setattr('simple_memory.call_model', fake_call)
    monkeypatch.setattr('simple_memory.resolve_provider_model', lambda r: {'model': 'fake'})
    mock_pair = {
        'turn_index': 2,
        'turn_id': 'turn-0002',
        'user': {'role': 'user', 'content': '翻墙进入山寨'},
        'assistant': {'role': 'assistant', 'content': '悄无声息避开暗哨。'},
    }
    monkeypatch.setattr('simple_memory.load_history_turn_pair', lambda _sid, _t: mock_pair)

    from simple_memory import generate_turn_summary
    res = generate_turn_summary(SESSION_P3, 2)
    # 确认上轮状态正确传给模型
    assert captured_previous_state.get('found') is True
    # 确认未修改字段继承了手动编辑后的目标
    assert res['state_after']['goal'] == '暗杀首领'


def test_failed_big_summary_regenerate_keeps_old_content_in_context(p3_env, monkeypatch):
    """
    验收测试 2：重新生成大总结失败时，旧内容仍留在记忆上下文中，不会永久消失。
    """
    # 清空超级总结，使大总结 B1 处于活跃呈现状态（不在超级总结之后被吸收）
    save_super_summaries(SESSION_P3, [])

    # 当前已有一份 B1 大总结，内容为 "## 剧情\n大总结1"
    ctx_before = build_memory_context(SESSION_P3)
    assert '大总结1' in ctx_before['big_summary_block']

    # 用户点击重新生成，标记为 regenerating
    h = DummyHandler()
    h._post_memory_big_summary_regenerate(None, {'session_id': SESSION_P3, 'index': 1, 'force': True})
    assert h.response_status == 200

    # 验证在重新生成进行中（regenerating=True），上下文依然能看到 B1 旧内容
    ctx_during = build_memory_context(SESSION_P3)
    assert '大总结1' in ctx_during['big_summary_block']

    # 模拟后台执行失败
    bigs = load_big_summaries(SESSION_P3)
    bigs[0]['status'] = 'failed'
    bigs[0]['regenerating'] = False
    bigs[0]['error'] = '网络超时'
    save_big_summaries(SESSION_P3, bigs)

    # 验证失败后，旧内容仍然留在记忆上下文里！
    ctx_after_failure = build_memory_context(SESSION_P3)
    assert '大总结1' in ctx_after_failure['big_summary_block']


def test_post_memory_state_waits_idle_outside_lock(p3_env, monkeypatch):
    """验证 /api/memory/state 在获取会话锁之前先 wait_idle。"""
    events = []
    fake_lock = server.session_lock(SESSION_P3)

    def spy_wait_idle(session_id, timeout_s=20.0):
        events.append(('wait_idle', fake_lock.locked()))
        return True

    monkeypatch.setattr('simple_memory.wait_idle', spy_wait_idle)
    h = DummyHandler()
    h._post_memory_state(None, {
        'session_id': SESSION_P3,
        'state': {'location': '新地点'},
    })
    assert h.response_status == 200
    assert len(events) == 1
    # 必须在锁外调用 wait_idle（即 locked() 为 False）
    assert events[0] == ('wait_idle', False)


def test_regenerate_old_turn_does_not_clear_latest_arbiter(p3_env, monkeypatch):
    """重新生成旧轮次小结时，传入 update_arbiter=False，不冲掉最新一轮的裁定结果。"""
    import simple_memory
    # 假设当前最新一轮是第 5 轮，带裁定结果
    simple_memory._LATEST_ARBITER[SESSION_P3] = (5, [{'event_id': 'evt_005'}])

    h = DummyHandler()
    # 重新生成第 1 轮
    h._post_memory_turn_summary_regenerate(None, {
        'session_id': SESSION_P3,
        'turn': 1,
        'force': True,
    })
    assert h.response_status == 200

    # 验证第 5 轮的裁定没有被冲掉成 (1, None)
    assert simple_memory._LATEST_ARBITER[SESSION_P3] == (5, [{'event_id': 'evt_005'}])

