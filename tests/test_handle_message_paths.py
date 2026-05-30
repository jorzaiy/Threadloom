"""Characterization tests for handler_message.handle_message.

handle_message is ~800 lines of central runtime orchestration with no direct
coverage (test_regenerate_turn mocks it wholesale). These tests drive the REAL
function through each branch with every external dependency (narrator LLM,
skeleton/state keepers, storage, context build, trackers) faked, asserting the
observable contract per path: which response shape comes back, whether history /
state / meta get committed, and idempotency caching. They are a safety net for
refactoring the function (e.g. extracting finalize_opening_choice), not a test
of the keepers themselves.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import handler_message as hm  # noqa: E402

NARRATOR_REPLY = '叙事正文回复。'


def _install_fakes(monkeypatch, *, state, meta, history=None):
    """Patch every external handle_message depends on with deterministic fakes
    that drive a successful runtime commit. Returns a ``spies`` dict recording
    the side effects (saved state/meta, appended history)."""
    spies = {'saved_state': [], 'saved_meta': [], 'appended': [], 'traces': [], 'events': []}
    history = list(history or [])

    def fake_append_history(_session_id, item):
        history.append(item)
        spies['appended'].append(item)

    patches = {
        # storage / trace
        'bootstrap_session': lambda _sid: None,
        'load_meta': lambda _sid: {**meta, 'processed_client_turn_ids': dict(meta.get('processed_client_turn_ids', {}))},
        'save_meta': lambda _sid, m: spies['saved_meta'].append({**m, 'processed_client_turn_ids': dict(m.get('processed_client_turn_ids', {}))}),
        'load_state': lambda _sid: dict(state),
        'save_state': lambda _sid, s: spies['saved_state'].append(dict(s)),
        'seed_default_state': lambda _sid: {},
        'load_history': lambda _sid: list(history),
        'append_history': fake_append_history,
        'build_state_snapshot': lambda s: {'_snapshot': True},
        'web_runtime_settings': lambda: {},
        'load_event_summaries': lambda _sid: {'items': []},
        'upsert_event_summary': lambda _sid, item: spies['events'].append(item),
        'update_summary_chunks': lambda _sid, **kw: {},
        'update_summary': lambda _sid: '# Summary',
        '_save_turn_trace_safe': lambda _sid, _tid, trace: spies['traces'].append(trace),
        # opening helpers (default: not an opening turn)
        'resolve_opening_choice': lambda _text: None,
        'is_opening_command': lambda _text: False,
        'build_opening_reply': lambda _text: 'OPENING-REPLY',
        'build_opening_choice_reply': lambda choice: f'OPENING-CHOICE:{choice}',
        'initialize_opening_state': lambda _sid: dict(state),
        'initialize_opening_choice_state': lambda _sid, choice, persist=False: dict(state),
        # runtime build / narrator
        'build_runtime_context': lambda _sid, user_text='': {
            'scene_facts': {'onstage_npcs': []},
            'continuity_candidates': [],
            'active_preset': {'name': 'test-preset'},
            'player_profile_json': {},
            'character_core': {},
            'context_audit': {},
            'lorebook_injection': {},
            'persona': [],
        },
        'run_arbiter': lambda _text, _scene: {'arbiter_needed': False, 'results': [], 'analysis': {}},
        'build_state_fragment': lambda *a, **k: {},
        'build_narrator_input': lambda *a, **k: ('SYS', 'USR'),
        'prompt_block_stats': lambda _sys: [],
        '_call_narrator_with_retries': lambda _sys, _usr: (
            NARRATOR_REPLY,
            {'model': 'fake', 'input_tokens': 1, 'output_tokens': 2, 'finish_reason': 'stop'},
            {'all_failed': False},
        ),
        'looks_incomplete_reply': lambda _reply: False,
        'load_runtime_config': lambda: {'memory': {'unified_transaction_enabled': True, 'consolidate_every_turns': 3}},
        '_is_object_heavy_turn': lambda *a, **k: False,
        'skeleton_keeper_enabled': lambda: False,
        'call_skeleton_keeper': lambda *a, **k: ({}, {}, {}),
        'merge_state_skeleton': lambda fragment, _skel: fragment,
        'merge_reply_skeleton': lambda fragment, _reply: fragment,
        'call_state_keeper': lambda _sid, _reply, **k: (dict(state, state_keeper_diagnostics={}), {'payload': {}}),
        'build_state_from_fragment': lambda s, _frag, _sid: dict(s, state_keeper_diagnostics={}),
        'retry_possession_keeper': lambda *a, **k: {},
        # post-keeper trackers (pass-through)
        'merge_arbiter_state': lambda s, _arb: s,
        'apply_thread_tracker': lambda s, **k: s,
        'normalized_hint_entries': lambda _sid: [],
        'update_important_npcs': lambda s, *a, **k: s,
        'resolve_important_npc_continuity': lambda s: s,
        '_add_lightweight_knowledge_delta': lambda s, _reply: s,
        'update_actor_registry': lambda s, **k: s,
        'canonicalize_state_memory': lambda s: (s, {}),
        'resolve_stale_state_threads': lambda s: (s, {}),
        # event / summary / persona / audit
        'build_event_ledger_with_llm': lambda **k: {},
        'extract_time_location_anchor': lambda *a, **k: ('', ''),
        'build_event_summary_item': lambda **k: {},
        'update_persona': lambda *a, **k: {},
        '_build_turn_audit': lambda *a, **k: {},
        '_store_turn_audit': lambda _meta, _audit: None,
        'run_session_audit': lambda *a, **k: {'severity': 'ok', 'summary': {'issue_count': 0}, 'issues': []},
    }
    for name, fake in patches.items():
        monkeypatch.setattr(hm, name, fake)
    return spies


def _payload(text='我走进房间', client_turn_id='', debug=False):
    return {'session_id': 'sess-001', 'text': text, 'client_turn_id': client_turn_id, 'meta': {'debug': debug}}


_RUNTIME_STATE = {'opening_resolved': True, 'opening_started': True, 'state_keeper_bootstrapped': True, 'actors': {}, 'onstage_npcs': []}


# ── runtime main path ────────────────────────────────────────────────────────

def test_successful_runtime_turn_commits_and_caches(monkeypatch):
    spies = _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    resp = hm.handle_message(_payload(client_turn_id='ct-9'))
    assert resp['reply'] == NARRATOR_REPLY
    assert resp['turn_id'] == 'turn-0006'
    assert 'error' not in resp
    assert 'turn_audit' in resp.get('meta', {})   # committed runtime response shape
    assert 'state_snapshot' in resp
    # committed exactly once, both user + assistant history items appended
    assert len(spies['saved_state']) == 1
    assert [item['role'] for item in spies['appended']] == ['user', 'assistant']
    # idempotency: the response is cached under the client_turn_id and turn advanced
    last_meta = spies['saved_meta'][-1]
    assert last_meta['last_turn_id'] == 6
    assert last_meta['processed_client_turn_ids']['ct-9']['reply'] == NARRATOR_REPLY
    # cached entry is slimmed (state_snapshot dropped; rehydrated on hit)
    assert 'state_snapshot' not in last_meta['processed_client_turn_ids']['ct-9']


def test_debug_flag_adds_debug_block(monkeypatch):
    _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 2, 'processed_client_turn_ids': {}})
    resp = hm.handle_message(_payload(debug=True))
    assert resp['debug']['scene_mode'] == 'runtime-loaded'


def test_idempotency_cache_hit_short_circuits(monkeypatch):
    # Cached entries are stored slim (no state_snapshot); the hit path rehydrates
    # the snapshot from current state so the replayed response keeps its shape.
    cached = {'reply': 'CACHED', 'turn_id': 'turn-0003'}
    spies = _install_fakes(
        monkeypatch,
        state=_RUNTIME_STATE,
        meta={'last_turn_id': 5, 'processed_client_turn_ids': {'ct-1': cached}},
    )
    resp = hm.handle_message(_payload(client_turn_id='ct-1'))
    assert resp['reply'] == 'CACHED'
    assert resp['turn_id'] == 'turn-0003'
    assert resp['state_snapshot'] == {'_snapshot': True}   # rehydrated from current state
    assert spies['saved_state'] == []          # nothing committed (no reprocessing)
    assert spies['appended'] == []             # no history written


def test_idempotency_hit_returns_legacy_entry_with_snapshot_verbatim(monkeypatch):
    # Backward compat: a pre-existing cached entry that still carries a
    # state_snapshot is returned as-is (no double rehydrate).
    cached = {'reply': 'OLD', 'turn_id': 'turn-0002', 'state_snapshot': {'legacy': True}}
    _install_fakes(
        monkeypatch,
        state=_RUNTIME_STATE,
        meta={'last_turn_id': 5, 'processed_client_turn_ids': {'ct-2': cached}},
    )
    resp = hm.handle_message(_payload(client_turn_id='ct-2'))
    assert resp == cached


def test_runtime_narrator_failure_returns_unavailable(monkeypatch):
    spies = _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, '_call_narrator_with_retries', lambda _s, _u: ('', {'finish_reason': 'error'}, {'all_failed': True, 'last_error': 'boom'}))
    resp = hm.handle_message(_payload())
    assert resp['error']['code'] == 'NARRATOR_UNAVAILABLE'
    assert spies['saved_state'] == []          # not committed


def test_runtime_partial_reply_returns_incomplete(monkeypatch):
    spies = _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, '_call_narrator_with_retries', lambda _s, _u: ('半截正文', {'finish_reason': 'length'}, {'all_failed': False}))
    resp = hm.handle_message(_payload())
    assert resp['error']['code'] == 'NARRATOR_INCOMPLETE'
    assert spies['saved_state'] == []


# ── opening paths ────────────────────────────────────────────────────────────

def test_opening_menu_guard_when_choice_not_recognized(monkeypatch):
    state = {'opening_mode': 'menu', 'opening_resolved': False}
    _install_fakes(monkeypatch, state=state, meta={'last_turn_id': 0, 'processed_client_turn_ids': {}})
    resp = hm.handle_message(_payload(text='随便说点什么'))
    assert resp['usage']['model'] == 'opening-menu-guard'
    assert '选择开局' in resp['reply']


def test_opening_menu_choice_drives_finalize_opening_choice(monkeypatch):
    # The path that runs the 178-line finalize_opening_choice closure end-to-end.
    state = {'opening_mode': 'menu', 'opening_resolved': False}
    spies = _install_fakes(monkeypatch, state=state, meta={'last_turn_id': 0, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, 'resolve_opening_choice', lambda _text: '开局一')
    resp = hm.handle_message(_payload(text='1'))
    assert resp['reply'] == NARRATOR_REPLY
    assert resp['turn_id'] == 'turn-0001'
    assert 'error' not in resp
    assert 'state_snapshot' in resp
    assert len(spies['saved_state']) == 1      # opening choice commits the bootstrapped turn
    # Opening flags must persist even though the (mocked) keeper rebuilt state from
    # the unsaved disk baseline with opening_resolved=False -- otherwise the next
    # turn falls back into the opening menu.
    saved = spies['saved_state'][-1]
    assert saved['opening_resolved'] is True
    assert saved['opening_started'] is True


def test_opening_choice_narrator_failure_does_not_commit(monkeypatch):
    state = {'opening_mode': 'menu', 'opening_resolved': False}
    spies = _install_fakes(monkeypatch, state=state, meta={'last_turn_id': 0, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, 'resolve_opening_choice', lambda _text: '开局一')
    monkeypatch.setattr(hm, '_call_narrator_with_retries', lambda _s, _u: ('', {'finish_reason': 'error'}, {'all_failed': True, 'last_error': 'boom'}))
    resp = hm.handle_message(_payload(text='1'))
    assert resp['error']['code'] == 'NARRATOR_UNAVAILABLE'
    assert spies['saved_state'] == []


def test_opening_command_on_first_turn(monkeypatch):
    _install_fakes(monkeypatch, state={'opening_resolved': False}, meta={'last_turn_id': 0, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, 'is_opening_command', lambda _text: True)
    resp = hm.handle_message(_payload(text='开始'))
    assert resp['usage']['model'] == 'opening'
    assert resp['reply'] == 'OPENING-REPLY'


def test_opening_guard_when_already_started(monkeypatch):
    state = {'opening_resolved': True, 'opening_started': True}
    _install_fakes(monkeypatch, state=state, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    monkeypatch.setattr(hm, 'is_opening_command', lambda _text: True)
    resp = hm.handle_message(_payload(text='开始'))
    assert resp['usage']['model'] == 'opening-guard'
    assert '已经开始' in resp['reply']


# ── periodic session audit (runs on consolidation turns) ─────────────────────

def test_session_audit_runs_on_consolidation_turn(monkeypatch):
    # turn 6 (last_turn_id 5) with consolidate_every=3 -> consolidation turn.
    _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    calls = []
    monkeypatch.setattr(hm, 'run_session_audit', lambda sid, **k: calls.append(sid) or {
        'severity': 'warning', 'summary': {'issue_count': 1},
        'issues': [{'type': 'style_drift', 'severity': 'warning', 'message': 'x'}],
    })
    resp = hm.handle_message(_payload(debug=True))
    assert calls == ['sess-001']
    assert resp['debug']['session_audit']['severity'] == 'warning'
    assert resp['debug']['session_audit']['issues'][0]['type'] == 'style_drift'


def test_session_audit_skipped_off_consolidation_turn(monkeypatch):
    # turn 4 (last_turn_id 3) with consolidate_every=3 -> NOT a consolidation turn.
    _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 3, 'processed_client_turn_ids': {}})
    calls = []
    monkeypatch.setattr(hm, 'run_session_audit', lambda sid, **k: calls.append(sid) or {})
    resp = hm.handle_message(_payload(debug=True))
    assert calls == []
    assert resp['debug'].get('session_audit') is None


def test_session_audit_failure_never_blocks_turn(monkeypatch):
    # A crashing auditor must not break the committed turn (diagnostic-only).
    spies = _install_fakes(monkeypatch, state=_RUNTIME_STATE, meta={'last_turn_id': 5, 'processed_client_turn_ids': {}})
    def boom(_sid, **k):
        raise RuntimeError('audit exploded')
    monkeypatch.setattr(hm, 'run_session_audit', boom)
    resp = hm.handle_message(_payload(debug=True))
    assert resp['reply'] == NARRATOR_REPLY      # turn still committed
    assert len(spies['saved_state']) == 1
    assert resp['debug'].get('session_audit') is None
