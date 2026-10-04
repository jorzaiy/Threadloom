#!/usr/bin/env python3
"""P2 回归测试：真实模板 + 小阈值 worker 全流程。

两项阻塞问题（模板 KeyError、请求与后台任务互等会话锁）原本都能被这两组测试提前发现。
所有模型调用都用假 call_model，不访问网络。
"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import simple_memory as sm  # noqa: E402


SESSION = 'p2-worker-session'


class FakeHistory:
    """按轮次保存 user/assistant 原文，替代 runtime_store.load_history_turn_pair。"""

    def __init__(self):
        self.pairs: dict[int, dict] = {}

    def add(self, turn: int, user: str, reply: str) -> None:
        self.pairs[turn] = {
            'turn_index': turn,
            'turn_id': f'turn-{turn:04d}',
            'user': {'role': 'user', 'content': user},
            'assistant': {'role': 'assistant', 'content': reply},
        }

    def delete(self, turn: int) -> None:
        self.pairs.pop(turn, None)

    def load(self, _session_id: str, turn: int) -> dict:
        return dict(self.pairs.get(turn, {}))


class FakeModel:
    """假 call_model：记录 prompt，按调用类型返回小结 JSON 或四栏 Markdown。"""

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls: list[dict] = []
        self.lock = threading.Lock()
        self.started = threading.Event()

    def __call__(self, cfg, system_prompt, user_prompt):
        self.started.set()
        if self.delay_s:
            time.sleep(self.delay_s)
        with self.lock:
            self.calls.append({'cfg': dict(cfg), 'system': system_prompt, 'user': user_prompt})
        if cfg.get('response_format'):
            return json.dumps({
                'summary': '主角与掌柜交谈。\n【设定】掌柜：凡人，无灵根',
                'state': {'time': '丑时', 'location': '悦来客栈', 'onstage': ['掌柜'], 'goal': '查阵法', 'risks': [], 'items': []},
            }, ensure_ascii=False), {'model': 'fake'}
        return ('## 剧情\n概要\n\n## 人物档案\n★ 掌柜：凡人\n\n## 未解线索\n铜钱来源\n\n## 设定\n客栈有阵法\n'), {'model': 'fake'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    history = FakeHistory()
    model = FakeModel()
    locks: dict[str, threading.Lock] = {}
    locks_guard = threading.Lock()

    def fake_session_lock(session_id):
        with locks_guard:
            return locks.setdefault(session_id, threading.Lock())

    monkeypatch.setattr(sm, 'resolve_session_dir', lambda sid, create=False: tmp_path / sid)
    monkeypatch.setattr(sm, 'load_history_turn_pair', history.load)
    monkeypatch.setattr(sm, 'call_model', model)
    monkeypatch.setattr(sm, 'resolve_provider_model', lambda role: {'model': f'fake-{role}', 'max_output_tokens': 4000})
    monkeypatch.setattr(sm, 'session_lock', fake_session_lock)
    monkeypatch.setattr(sm, '_memory_thresholds', lambda: (2, 2))  # big_every=2, super_every=2
    yield {'history': history, 'model': model, 'lock': fake_session_lock, 'tmp': tmp_path}
    sm.wait_idle(SESSION, timeout_s=5)


def _commit_turn(env, turn: int, *, user: str = '继续', reply: str | None = None, arbiter=None):
    """模拟 handle_message 的提交尾部：写历史 + pending 占位 + enqueue。"""
    reply = reply if reply is not None else f'第{turn}轮叙事'
    env['history'].add(turn, user, reply)
    import hashlib
    sm.upsert_turn_summary(SESSION, {
        'turn': turn,
        'turn_id': f'turn-{turn:04d}',
        'reply_hash': hashlib.sha1(reply.encode('utf-8')).hexdigest(),
        'status': 'pending',
        'summary': '',
        'state_after': sm.load_simple_state(SESSION),
        'edited': False,
        'error': '',
        'model': '',
        'updated_at': int(time.time() * 1000),
    })
    sm.enqueue_after_turn(SESSION, turn, arbiter_result=arbiter)


# ---------------------------------------------------------------------------
# 1. 真实模板
# ---------------------------------------------------------------------------

def test_generate_turn_summary_with_real_template(env):
    """用仓库里真实的 prompts/memory/turn-summary.md 调一次，不能抛 KeyError。"""
    template = sm._load_prompt_template('turn-summary.md')
    assert '{user_input}' in template and '"summary"' in template, '必须测真实模板'

    # 用户输入和回复里故意带花括号 / 占位符样式文本，验证不会被二次解析
    tricky_user = '我说："{narrator_reply}" 然后看着 {"key": 1}'
    env['history'].add(1, tricky_user, '掌柜笑道：{无事}。')

    rec = sm.generate_turn_summary(SESSION, 1, arbiter_result=[{'event': 'check'}])

    assert rec['status'] == 'ok'
    assert '【设定】掌柜：凡人' in rec['summary']
    assert rec['state_after']['location'] == '悦来客栈'

    prompt = env['model'].calls[-1]['user']
    # 已知占位符全部被替换
    for key in ('{character_core_brief}', '{recent_turn_summaries}', '{big_summary_profiles}',
                '{previous_state}', '{user_input}', '{narrator_reply}'):
        assert key not in prompt.replace(tricky_user, ''), key
    # 用户原文按字面保留（里面的 {narrator_reply} 没被替换成回复）
    assert tricky_user in prompt
    assert '掌柜笑道：{无事}。' in prompt
    # 模板里的 JSON 输出示例原样保留
    assert '"summary":' in prompt and '"state":' in prompt
    # 裁定结果作为参考输入传入
    assert '本轮裁定结果' in prompt
    # 小结调用要求 JSON 输出
    assert env['model'].calls[-1]['cfg'].get('response_format') == {'type': 'json_object'}


def test_all_three_real_templates_fill_without_error():
    for name, keys in {
        'turn-summary.md': ['character_core_brief', 'recent_turn_summaries', 'big_summary_profiles',
                            'previous_state', 'user_input', 'narrator_reply'],
        'big-summary.md': ['previous_big_summary', 'interval_turn_summaries', 'current_state'],
        'super-summary.md': ['previous_super_summary', 'interval_big_summaries'],
    }.items():
        template = sm._load_prompt_template(name)
        assert template, name
        filled = sm.fill_prompt_template(template, **{k: f'<{k}>' for k in keys})
        for k in keys:
            assert f'{{{k}}}' not in filled, (name, k)
            assert f'<{k}>' in filled, (name, k)


# ---------------------------------------------------------------------------
# 2. 小阈值 worker 全流程
# ---------------------------------------------------------------------------

def test_worker_full_flow_small_thresholds(env):
    """big_every=2, super_every=2：4 轮后应有 2 份大总结 + 1 份超级总结。"""
    for turn in range(1, 5):
        _commit_turn(env, turn)
        assert sm.wait_idle(SESSION, timeout_s=5)

    turns = sm.load_turn_summaries(SESSION)
    assert [t['turn'] for t in turns] == [1, 2, 3, 4]
    assert all(t['status'] == 'ok' for t in turns), turns
    # state.json 跟着最新一轮更新（新格式）
    state = sm.load_simple_state(SESSION)
    assert state['location'] == '悦来客栈' and 'onstage' in state

    bigs = sm.load_big_summaries(SESSION)
    assert [(b['turn_start'], b['turn_end']) for b in bigs] == [(1, 2), (3, 4)]
    supers = sm.load_super_summaries(SESSION)
    assert len(supers) == 1 and supers[0]['big_range'] == [1, 2]
    assert (supers[0]['turn_start'], supers[0]['turn_end']) == (1, 4)

    # 上下文按 5.3 切换：超级总结覆盖 1-4，大总结区块为空，小结从 covered_end-9 起
    ctx = sm.build_memory_context(SESSION, current_turn=4)
    assert ctx['super_summary_block']
    assert ctx['big_summary_block'] == ''
    assert '第1轮：' in ctx['turn_summary_block'] and '第4轮：' in ctx['turn_summary_block']


def test_big_summary_triggers_by_turn_even_if_a_summary_failed(env):
    """有一条小结彻底失败时，到达轮次仍然生成大总结，缺失的轮次用原文代替。"""
    real_model = env['model']

    def flaky(cfg, system_prompt, user_prompt):
        if cfg.get('response_format') and '第1轮叙事' in user_prompt:
            raise RuntimeError('model down')
        return real_model(cfg, system_prompt, user_prompt)

    sm.call_model = flaky  # monkeypatch 已在 fixture 里登记，teardown 会恢复
    for turn in (1, 2):
        _commit_turn(env, turn)
        assert sm.wait_idle(SESSION, timeout_s=5)
    # 让第 1 轮耗尽 3 次重试
    for _ in range(3):
        sm.enqueue_after_turn(SESSION, 2)
        assert sm.wait_idle(SESSION, timeout_s=5)

    t1 = next(t for t in sm.load_turn_summaries(SESSION) if t['turn'] == 1)
    assert t1['status'] == 'failed' and t1['retry_count'] >= 3

    bigs = sm.load_big_summaries(SESSION)
    assert len(bigs) == 1 and (bigs[0]['turn_start'], bigs[0]['turn_end']) == (1, 2)
    big_prompt = next(c['user'] for c in real_model.calls if not c['cfg'].get('response_format'))
    assert '第1轮小结缺失' in big_prompt and '第1轮叙事' in big_prompt


def test_arbiter_result_only_goes_to_latest_turn(env):
    env['model'].delay_s = 0.3
    _commit_turn(env, 1, arbiter=None)
    assert env['model'].started.wait(2)
    # 第 1 轮还在生成时提交第 2、3 轮，第 3 轮带裁定结果
    _commit_turn(env, 2, arbiter=None)
    _commit_turn(env, 3, arbiter=[{'event_id': 'E3'}])
    assert sm.wait_idle(SESSION, timeout_s=10)

    by_turn = {}
    for c in env['model'].calls:
        if c['cfg'].get('response_format'):
            for t in (1, 2, 3):
                if f'第{t}轮叙事' in c['user']:
                    by_turn[t] = c['user']
    assert set(by_turn) == {1, 2, 3}
    assert 'E3' in by_turn[3]
    assert 'E3' not in by_turn[1] and 'E3' not in by_turn[2]


def test_deleted_turn_is_not_resurrected_by_failed_job(env):
    """生成中途该轮被删除：失败分支也不能把记录写回来。"""
    started, release = threading.Event(), threading.Event()

    def blocking_fail(cfg, system_prompt, user_prompt):
        started.set()
        release.wait(5)
        raise RuntimeError('boom')

    sm.call_model = blocking_fail
    _commit_turn(env, 1)
    assert started.wait(2)
    # 模拟删除最新一轮（server 里是在锁外 cancel_and_wait、锁内回滚）
    with env['lock'](SESSION):
        env['history'].delete(1)
        sm.delete_turn_summaries_from(SESSION, 1)
    release.set()
    assert sm.wait_idle(SESSION, timeout_s=5)
    assert sm.load_turn_summaries(SESSION) == []


def test_next_message_during_summary_does_not_wait_full_timeout(env, monkeypatch):
    """小结生成中途收到下一条消息：

    - 走真实的 server.Handler._post_message，验证 wait_idle 在拿会话锁之前调用；
    - 整个请求耗时远小于 20 秒；
    - 新一轮不会被跳过，小结在本轮任务链里补齐。
    """
    import server

    env['model'].delay_s = 0.5
    _commit_turn(env, 1)
    assert env['model'].started.wait(2), '后台小结任务应该已经开始'

    observed = {}
    real_wait_idle = sm.wait_idle

    def spy_wait_idle(session_id, timeout_s=20.0):
        lock = env['lock'](session_id)
        observed['lock_held_during_wait'] = lock.locked()
        observed['timeout_s'] = timeout_s
        return real_wait_idle(session_id, timeout_s=timeout_s)

    def fake_handle_message(payload):
        observed['lock_held_during_handle'] = env['lock'](SESSION).locked()
        _commit_turn(env, 2)
        return {'session_id': SESSION, 'turn_id': 'turn-0002', 'reply': 'ok'}

    monkeypatch.setattr(server, 'wait_idle', spy_wait_idle)
    monkeypatch.setattr(server, 'handle_message', fake_handle_message)

    class FakeHandler:
        def _resolve_scoped_session(self, raw, *, allow_missing):
            return raw

        def _session_lock(self, session_id):
            return env['lock'](session_id)

        def _send(self, status, payload):
            observed['status'] = status
            return True

    start = time.monotonic()
    server.Handler._post_message(FakeHandler(), None, {'session_id': SESSION, 'text': '下一句'})
    elapsed = time.monotonic() - start

    assert observed['status'] == 200
    assert observed['lock_held_during_wait'] is False, 'wait_idle 必须在拿会话锁之前调用'
    assert observed['lock_held_during_handle'] is True
    assert elapsed < 5, f'请求等待了 {elapsed:.1f}s，不应接近 20s 超时'

    # 第 2 轮在第 1 轮任务运行时 enqueue，不能被跳过
    assert sm.wait_idle(SESSION, timeout_s=10)
    turns = {t['turn']: t['status'] for t in sm.load_turn_summaries(SESSION)}
    assert turns == {1: 'ok', 2: 'ok'}


def test_old_in_lock_wait_would_deadlock_until_timeout(env):
    """对照：如果在持锁状态下 wait_idle，后台提交拿不到锁，只能等到超时。"""
    env['model'].delay_s = 0.2
    _commit_turn(env, 1)
    assert env['model'].started.wait(2)
    with env['lock'](SESSION):
        start = time.monotonic()
        finished = sm.wait_idle(SESSION, timeout_s=1.0)
        elapsed = time.monotonic() - start
    assert finished is False and elapsed >= 0.9
    assert sm.wait_idle(SESSION, timeout_s=5)
