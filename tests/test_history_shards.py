#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from context_builder import build_history_evidence_pack  # noqa: E402
from runtime_store import invalidate_history_cache, load_history, load_history_manifest, load_history_pair_count, load_history_turn_pair, load_recent_history, save_history, session_paths  # noqa: E402


def _history_pairs(count: int) -> list[dict]:
    items = []
    for idx in range(1, count + 1):
        items.append({'role': 'user', 'content': f'用户动作{idx}'})
        items.append({'role': 'assistant', 'content': f'叙事正文{idx}', 'completion_status': 'complete'})
    return items


def test_save_history_writes_24_turn_shards_and_manifest(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s1', _history_pairs(25))

    paths = session_paths('s1')
    manifest = load_history_manifest('s1')

    assert manifest['shard_size'] == 24
    assert manifest['current_turn_end'] == 25
    assert [item['path'] for item in manifest['shards']] == [
        'history_shards/turns-000001-000024.jsonl',
        'history_shards/turns-000025-000048.jsonl',
    ]
    assert (paths['history_shards_dir'] / 'turns-000001-000024.jsonl').exists()
    assert (paths['history_shards_dir'] / 'turns-000025-000048.jsonl').exists()


def test_load_recent_history_reads_only_needed_shards(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s2', _history_pairs(30))

    recent = load_recent_history('s2', 6)

    assert [item['content'] for item in recent if item['role'] == 'user'] == [f'用户动作{idx}' for idx in range(25, 31)]
    assert [item['content'] for item in recent if item['role'] == 'assistant'] == [f'叙事正文{idx}' for idx in range(25, 31)]


def test_history_evidence_pack_can_hydrate_from_shard_without_full_history(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    history = _history_pairs(25)
    history[48]['content'] = '询问药铺掌柜井里的东西'
    history[49]['content'] = '药铺掌柜说井边暗红泥屑早年见过，但没人说沈青到过井边。'
    save_history('s3', history)

    pair = load_history_turn_pair('s3', 25)
    assert pair['assistant']['content'].startswith('药铺掌柜说')

    pack = build_history_evidence_pack(
        selected_events=[{
            'event_id': 'evt_0025',
            'turn_id': 'turn-0025',
            'summary': '药铺掌柜提到井边暗红泥屑。',
            'clues': ['井边暗红泥屑'],
        }],
        event_hits=[{'event_id': 'evt_0025', 'reason': 'long_range_background'}],
        user_text='沈青经脉残留和井里的东西是什么关系？',
        session_id='s3',
    )

    assert len(pack['items']) == 1
    assert pack['items'][0]['source'] == 'turn-0025'
    assert '没人说沈青到过井边' in pack['items'][0]['assistant_excerpt']


def test_stale_manifest_rebuilds_from_legacy_history(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s4', _history_pairs(30))
    paths = session_paths('s4')
    history = _history_pairs(31)
    paths['history'].write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in history), encoding='utf-8')
    invalidate_history_cache('s4')
    old_time = paths['history'].stat().st_mtime - 10
    os.utime(paths['history_manifest'], (old_time, old_time))

    assert load_history_pair_count('s4') == 31
    recent = load_recent_history('s4', 2)
    assert [item['content'] for item in recent if item['role'] == 'assistant'] == ['叙事正文30', '叙事正文31']


def test_missing_needed_shard_falls_back_to_legacy_recent_history(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s5', _history_pairs(30))
    paths = session_paths('s5')
    (paths['history_shards_dir'] / 'turns-000025-000048.jsonl').unlink()
    manifest_time = paths['history'].stat().st_mtime + 10
    os.utime(paths['history_manifest'], (manifest_time, manifest_time))

    recent = load_recent_history('s5', 6)

    assert [item['content'] for item in recent if item['role'] == 'assistant'] == [f'叙事正文{idx}' for idx in range(25, 31)]


def test_shards_overwrite_stale_turn_ids_with_canonical_ids(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    history = _history_pairs(2)
    history[2]['turn_id'] = 'turn-9999'
    history[3]['turn_id'] = 'turn-9999'
    save_history('s6', history)

    pair = load_history_turn_pair('s6', 2)

    assert pair['turn_id'] == 'turn-0002'
    assert pair['user']['turn_id'] == 'turn-0002'
    assert pair['assistant']['turn_id'] == 'turn-0002'


def test_incomplete_assistant_in_needed_shard_falls_back_to_legacy(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s7', _history_pairs(30))
    paths = session_paths('s7')
    shard_path = paths['history_shards_dir'] / 'turns-000025-000048.jsonl'
    shard_items = [json.loads(line) for line in shard_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    for item in shard_items:
        if item.get('turn_id') == 'turn-0030' and item.get('role') == 'assistant':
            item['completion_status'] = 'partial'
            item['content'] = '不完整正文30'
    shard_path.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in shard_items), encoding='utf-8')
    manifest_time = paths['history'].stat().st_mtime + 10
    os.utime(paths['history_manifest'], (manifest_time, manifest_time))

    recent = load_recent_history('s7', 2)

    assert [item['content'] for item in recent if item['role'] == 'assistant'] == ['叙事正文29', '叙事正文30']


def test_load_history_can_reconstruct_from_shards_when_legacy_file_missing(tmp_path, monkeypatch):
    import runtime_store

    session_root = tmp_path / 'sessions'
    monkeypatch.setattr(runtime_store, 'resolve_session_dir', lambda session_id, create=False: session_root / session_id)

    save_history('s8', _history_pairs(2))
    paths = session_paths('s8')
    paths['history'].unlink()
    invalidate_history_cache('s8')

    history = load_history('s8')

    assert [item['content'] for item in history] == ['用户动作1', '叙事正文1', '用户动作2', '叙事正文2']
