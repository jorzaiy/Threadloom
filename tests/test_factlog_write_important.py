"""WRITE_IMPORTANT dual-track cutover: flag off = legacy, flag on = project merge."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

handler = importlib.import_module('handler_message')
fact_log = importlib.import_module('fact_log')


@pytest.fixture
def memory_session(tmp_path, monkeypatch):
    session_id = 'factlog-write-sess'
    session_dir = tmp_path / 'session'
    memory_dir = session_dir / 'memory'
    memory_dir.mkdir(parents=True)
    paths = {
        'session_dir': session_dir,
        'memory_dir': memory_dir,
    }
    monkeypatch.setattr(handler, 'session_paths', lambda _sid: paths)
    return session_id, memory_dir, session_dir


def test_flag_default_off():
    os.environ.pop('THREADLOOM_FACTLOG_WRITE_IMPORTANT', None)
    assert handler._factlog_write_important_enabled() is False


def test_write_important_merges_distinct_last_events(memory_session, monkeypatch):
    session_id, memory_dir, session_dir = memory_session
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '1')

    prev = {
        'important_npcs': [{
            'key': 'important:张麻子',
            'primary_label': '张麻子',
            'aliases': ['张叔'],
            'role_label': '门卫',
            'locked': True,
            'importance_score': 6,
            'last_main_event': '会被 clobber 的旧值',
            'present_now': False,
            'inactive_turns': 1,
        }],
    }
    # Two-turn log so 张麻子 is not ephemeral; 灵貂 is current onstage.
    log = fact_log.FactLog()
    log.commit_turn({
        'location': '北门',
        'main_event': '张麻子在北门盘问路引。',
        'onstage_npcs': ['张麻子'],
    }, 1)
    log.save(memory_dir)

    state = {
        'location': '东巷',
        'main_event': '触手从门缝探出拦路。',
        'onstage_npcs': ['灵貂'],
        'important_npcs': list(prev['important_npcs']),
        'scene_entities': [],
        'actors': {},
        'knowledge_scope': {},
    }
    out = handler._commit_fact_log_turn(
        session_id, 'turn-0002', 2, prev, state, write_important=True,
    )
    by = {n['primary_label']: n for n in out['important_npcs']}
    assert '张麻子' in by
    assert '灵貂' in by
    assert by['张麻子']['last_main_event'] == '张麻子在北门盘问路引。'
    assert by['灵貂']['last_main_event'] == '触手从门缝探出拦路。'
    assert by['张麻子']['role_label'] == '门卫'
    assert by['张麻子']['importance_score'] == 6
    assert '张叔' in by['张麻子']['aliases']
    assert by['张麻子']['locked'] is True
    # distinct events — not one clobbered main_event
    assert len({n['last_main_event'] for n in out['important_npcs']}) >= 2

    shadow = (session_dir / 'diagnostics' / 'factlog_shadow.jsonl').read_text(encoding='utf-8').strip()
    record = json.loads(shadow.splitlines()[-1])
    assert record['wrote_important'] is True


def test_write_important_failure_keeps_prior_roster(memory_session, monkeypatch):
    session_id, memory_dir, _session_dir = memory_session
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '1')

    prior = [{
        'key': 'important:掌柜',
        'primary_label': '掌柜',
        'locked': True,
        'last_main_event': '掌柜招呼客人。',
    }]
    state = {
        'location': '店',
        'main_event': '新事件',
        'onstage_npcs': ['掌柜'],
        'important_npcs': prior,
        'scene_entities': [],
        'actors': {},
        'knowledge_scope': {},
    }

    def boom(*_a, **_k):
        raise RuntimeError('merge exploded')

    monkeypatch.setattr(handler, 'merge_projected_important_npcs', boom)
    out = handler._commit_fact_log_turn(
        session_id, 'turn-0001', 1, {}, state, write_important=True,
    )
    assert out['important_npcs'] is prior
    assert out['important_npcs'][0]['last_main_event'] == '掌柜招呼客人。'


def test_flag_off_does_not_mutate_important(memory_session, monkeypatch):
    session_id, memory_dir, session_dir = memory_session
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '0')
    state = {
        'location': '街',
        'main_event': '掌柜搭话',
        'onstage_npcs': ['掌柜'],
        'important_npcs': [{'primary_label': '旧名单', 'last_main_event': '旧'}],
        'scene_entities': [],
        'actors': {},
        'knowledge_scope': {},
    }
    out = handler._commit_fact_log_turn(
        session_id, 'turn-0001', 1, {}, state, write_important=False,
    )
    assert out['important_npcs'][0]['primary_label'] == '旧名单'
    assert (memory_dir / 'facts.jsonl').exists()
    shadow = (session_dir / 'diagnostics' / 'factlog_shadow.jsonl').read_text(encoding='utf-8').strip()
    record = json.loads(shadow.splitlines()[-1])
    assert record['wrote_important'] is False


def test_apply_trackers_skipped_when_flag_on(monkeypatch):
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '1')
    called = {'tracker': 0, 'continuity': 0}

    def fake_tracker(state, *_a, **_k):
        called['tracker'] += 1
        state = dict(state)
        state['important_npcs'] = [{'primary_label': 'from-tracker'}]
        return state

    def fake_continuity(state):
        called['continuity'] += 1
        return state

    monkeypatch.setattr(handler, 'update_important_npcs', fake_tracker)
    monkeypatch.setattr(handler, 'resolve_important_npc_continuity', fake_continuity)
    monkeypatch.setattr(handler, 'load_history', lambda _sid: [])

    state = {'important_npcs': [{'primary_label': 'keep-me'}]}
    out = handler._apply_important_npc_trackers(state, 's', {})
    assert called == {'tracker': 0, 'continuity': 0}
    assert out['important_npcs'][0]['primary_label'] == 'keep-me'


def test_apply_trackers_run_when_flag_off(monkeypatch):
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '0')
    called = {'tracker': 0, 'continuity': 0}

    def fake_tracker(state, *_a, **_k):
        called['tracker'] += 1
        return state

    def fake_continuity(state):
        called['continuity'] += 1
        return state

    monkeypatch.setattr(handler, 'update_important_npcs', fake_tracker)
    monkeypatch.setattr(handler, 'resolve_important_npc_continuity', fake_continuity)
    monkeypatch.setattr(handler, 'load_history', lambda _sid: [])

    handler._apply_important_npc_trackers({}, 's', {})
    assert called == {'tracker': 1, 'continuity': 1}


def test_ephemeral_not_in_writeback_roster(memory_session, monkeypatch):
    session_id, memory_dir, _ = memory_session
    monkeypatch.setenv('THREADLOOM_FACTLOG_WRITE_IMPORTANT', '1')
    # present once then gone ≥2 turns → ephemeral, not long-term important
    log = fact_log.FactLog()
    log.commit_turn({'location': '街', 'main_event': '路人甲路过', 'onstage_npcs': ['路人甲']}, 1)
    log.commit_turn({'location': '街', 'main_event': '掌柜说话', 'onstage_npcs': ['掌柜']}, 2)
    log.save(memory_dir)
    state = {
        'location': '街',
        'main_event': '掌柜继续',
        'onstage_npcs': ['掌柜'],
        'important_npcs': [],
        'scene_entities': [],
        'actors': {},
        'knowledge_scope': {},
    }
    out = handler._commit_fact_log_turn(
        session_id, 'turn-0003', 3, {}, state, write_important=True,
    )
    labels = {n['primary_label'] for n in out['important_npcs']}
    assert '路人甲' not in labels
    assert '掌柜' in labels
