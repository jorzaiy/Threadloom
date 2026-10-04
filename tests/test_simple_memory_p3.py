#!/usr/bin/env python3
"""
P3 接口与交互单元测试：
1. GET /api/memory：返回 state、三层总结、任务状态及进度
2. POST /api/memory/state：编辑当前状态
3. POST /api/memory/turn-summary：编辑小结，标记 edited=true 及大总结 stale
4. POST /api/memory/turn-summary/regenerate：重写小结（edited 保护与 409，带 force 放行）
5. POST /api/memory/big-summary：编辑大总结
6. POST /api/memory/big-summary/regenerate：重新生成大总结
7. POST /api/memory/super-summary & regenerate
8. 长度校验与参数校验
"""
import json
import pytest
from pathlib import Path

from simple_memory import (
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
from server import Handler


SESSION_P3 = 'p3_test_session'


class DummyHandler(Handler):
    """测试专用的 Dummy 请求处理器，模拟路由派发。"""
    def __init__(self, user_id='default-user'):
        self.headers = {'Authorization': 'Bearer test-token'}
        self.client_address = ('127.0.0.1', 8000)
        self.response_status = None
        self.response_data = None
        self._test_user_id = user_id

    def _extract_token(self):
        return 'test-token'

    def _resolve_user_id(self, token):
        return self._test_user_id

    def _resolve_scoped_session(self, raw, allow_missing=False):
        return raw or SESSION_P3

    def _send(self, status, payload):
        self.response_status = status
        self.response_data = payload
        return payload

    def _send_raw(self, status, body, content_type=''):
        self.response_status = status
        self.response_data = body
        return body


@pytest.fixture
def p3_env(tmp_path, monkeypatch):
    monkeypatch.setattr('simple_memory.resolve_session_dir', lambda sid, create=False: tmp_path / sid)
    monkeypatch.setattr('paths.resolve_session_dir', lambda sid, create=False: tmp_path / sid)
    monkeypatch.setattr('server.resolve_session_dir', lambda sid, create=False: tmp_path / sid)

    # 初始化测试数据
    save_simple_state(SESSION_P3, {
        'time': '午时',
        'location': '青州城',
        'onstage': ['掌柜'],
        'goal': '收集情报',
        'risks': ['暴露'],
        'items': [{'name': '铜钱', 'holder': '掌柜'}],
        'secrets': [{'content': '秘密1', 'owner': '掌柜', 'knowers': ['掌柜']}],
    })

    upsert_turn_summary(SESSION_P3, {
        'turn': 1,
        'turn_id': 'turn-0001',
        'status': 'ok',
        'summary': '第1轮小结',
    })

    save_big_summaries(SESSION_P3, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 100,
        'status': 'ok',
        'content': '## 剧情\n大总结1',
        'edited': False,
        'stale': False,
    }])

    save_super_summaries(SESSION_P3, [{
        'index': 1,
        'turn_start': 1,
        'turn_end': 500,
        'big_range': [1, 5],
        'status': 'ok',
        'content': '## 剧情\n超级总结1',
        'edited': False,
    }])

    yield {'tmp': tmp_path}
    from simple_memory import cancel_and_wait
    cancel_and_wait(SESSION_P3)


def test_get_memory_api(p3_env):
    h = DummyHandler()
    h._get_memory(None, {'session_id': [SESSION_P3]})
    assert h.response_status == 200
    res = h.response_data
    assert res['session_id'] == SESSION_P3
    assert res['state']['location'] == '青州城'
    assert len(res['turn_summaries']) == 1
    assert len(res['big_summaries']) == 1
    assert len(res['super_summaries']) == 1
    assert '小结' in res['progress']['big_summary']


def test_post_memory_state_api(p3_env):
    h = DummyHandler()
    new_state = {
        'time': '戌时',
        'location': '客栈后山',
        'onstage': ['陆小环'],
        'goal': '逃离',
        'risks': ['追兵'],
        'items': [],
        'secrets': [],
    }
    h._post_memory_state(None, {'session_id': SESSION_P3, 'state': new_state})
    assert h.response_status == 200
    assert h.response_data['state']['location'] == '客栈后山'
    assert h.response_data['state']['time'] == '戌时'
    # 验证真实保存成功
    loaded = load_simple_state(SESSION_P3)
    assert loaded['location'] == '客栈后山'


def test_post_turn_summary_edit_and_stale_flag(p3_env):
    h = DummyHandler()
    # 编辑第 1 轮小结（此时第 1 轮属于大总结 B1 范围内）
    h._post_memory_turn_summary(None, {
        'session_id': SESSION_P3,
        'turn': 1,
        'summary': '已手动修改的小结内容',
    })
    assert h.response_status == 200
    turns = load_turn_summaries(SESSION_P3)
    assert turns[0]['summary'] == '已手动修改的小结内容'
    assert turns[0]['edited'] is True

    # 验证 B1 被自动标记为 stale=true
    bigs = load_big_summaries(SESSION_P3)
    assert bigs[0]['stale'] is True


def test_post_turn_summary_regenerate_conflict_and_force(p3_env, monkeypatch):
    h = DummyHandler()
    called = []
    monkeypatch.setattr('simple_memory.enqueue_after_turn', lambda sid, turn, *a, **k: called.append(turn))

    # 先编辑
    h._post_memory_turn_summary(None, {'session_id': SESSION_P3, 'turn': 1, 'summary': '手动编辑'})

    # 尝试重写，不带 force 返回 409
    h._post_memory_turn_summary_regenerate(None, {'session_id': SESSION_P3, 'turn': 1, 'force': False})
    assert h.response_status == 409
    assert called == []

    # 带 force 放行，进入主 worker 队列
    h._post_memory_turn_summary_regenerate(None, {'session_id': SESSION_P3, 'turn': 1, 'force': True})
    assert h.response_status == 200
    assert called == [1]


def test_post_big_summary_edit_and_regenerate(p3_env, monkeypatch):
    h = DummyHandler()
    called = []
    monkeypatch.setattr('simple_memory.enqueue_regenerate_job', lambda sid, jtype, idx: called.append((jtype, idx)))

    # 编辑
    h._post_memory_big_summary(None, {'session_id': SESSION_P3, 'index': 1, 'content': '## 剧情\n大总结已改'})
    assert h.response_status == 200
    bigs = load_big_summaries(SESSION_P3)
    assert '大总结已改' in bigs[0]['content']
    assert bigs[0]['edited'] is True

    # 重写冲突 409
    h._post_memory_big_summary_regenerate(None, {'session_id': SESSION_P3, 'index': 1, 'force': False})
    assert h.response_status == 409

    # 带 force 进入主 worker 调度队列
    h._post_memory_big_summary_regenerate(None, {'session_id': SESSION_P3, 'index': 1, 'force': True})
    assert h.response_status == 200
    assert called == [('big_summary', 1)]


def test_post_super_summary_edit_and_regenerate(p3_env, monkeypatch):
    h = DummyHandler()
    called = []
    monkeypatch.setattr('simple_memory.enqueue_regenerate_job', lambda sid, jtype, idx: called.append((jtype, idx)))

    # 编辑
    h._post_memory_super_summary(None, {'session_id': SESSION_P3, 'index': 1, 'content': '## 剧情\n超级总结已改'})
    assert h.response_status == 200
    supers = load_super_summaries(SESSION_P3)
    assert '超级总结已改' in supers[0]['content']
    assert supers[0]['edited'] is True

    # 重写冲突 409
    h._post_memory_super_summary_regenerate(None, {'session_id': SESSION_P3, 'index': 1, 'force': False})
    assert h.response_status == 409

    # 带 force
    h._post_memory_super_summary_regenerate(None, {'session_id': SESSION_P3, 'index': 1, 'force': True})
    assert h.response_status == 200
    assert called == [('super_summary', 1)]


def test_api_input_length_limits(p3_env):
    h = DummyHandler()
    # 小结 > 4000
    too_long_summary = "长文本" * 2000
    h._post_memory_turn_summary(None, {'session_id': SESSION_P3, 'turn': 1, 'summary': too_long_summary})
    assert h.response_status == 400

    # 大总结 > 30000
    too_long_big = "大文本" * 16000
    h._post_memory_big_summary(None, {'session_id': SESSION_P3, 'index': 1, 'content': too_long_big})
    assert h.response_status == 400
