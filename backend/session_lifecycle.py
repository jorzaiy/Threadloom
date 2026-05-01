#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path

try:
    from .bootstrap_session import load_runtime_config, resolve_source, read_json, read_text
    from .opening import build_opening_reply, initialize_opening_state
    from .paths import DEFAULT_USER_ID, active_user_id, current_session_owner_context, current_sessions_root, iter_session_dirs, normalize_session_id, resolve_session_dir
    from .runtime_store import append_history, build_state_snapshot, ensure_session_dirs, save_canon, save_context, save_meta, save_state, session_paths
    from .user_manager import is_multi_user_enabled
except ImportError:
    from bootstrap_session import load_runtime_config, resolve_source, read_json, read_text
    from opening import build_opening_reply, initialize_opening_state
    from paths import DEFAULT_USER_ID, active_user_id, current_session_owner_context, current_sessions_root, iter_session_dirs, normalize_session_id, resolve_session_dir
    from runtime_store import append_history, build_state_snapshot, ensure_session_dirs, save_canon, save_context, save_meta, save_state, session_paths
    from user_manager import is_multi_user_enabled


ROOT = Path(__file__).resolve().parents[2]

# Multi-user resource ceilings. Default-user (admin) is exempt; ordinary users
# are bounded so a single account cannot exhaust disk/memory by spawning an
# unbounded number of game sessions per character.
MAX_SESSIONS_PER_CHARACTER_FOR_USER = 50


def _enforce_session_quota() -> None:
    if not is_multi_user_enabled():
        return
    if active_user_id() == DEFAULT_USER_ID:
        return
    root = current_sessions_root()
    if not root.exists():
        return
    count = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith('archive-'):
            continue
        count += 1
        if count >= MAX_SESSIONS_PER_CHARACTER_FOR_USER:
            raise ValueError(
                f'session quota exhausted: at most {MAX_SESSIONS_PER_CHARACTER_FOR_USER} sessions per character'
            )


def _character_session_prefix() -> str:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    character_path = resolve_source(sources.get('character_core', 'character/character-data.json'))
    data = read_json(character_path)
    name = str(data.get('name', '') or '').strip() or 'story'
    safe = re.sub(r'[\\/:\s]+', '-', name)
    safe = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff]+', '', safe)
    return safe or 'story'


def _new_session_id(previous_session_id: str) -> str:
    stamp = time.strftime('%Y%m%d')
    suffix = secrets.token_hex(3)
    return f'{_character_session_prefix()}-{stamp}-{suffix}'


def _session_updated_at(session_dir: Path) -> int:
    candidates = [
        session_dir / 'memory' / 'history.jsonl',
        session_dir / 'memory' / 'state.json',
        session_dir / 'memory' / 'summary.md',
        session_dir / 'context.json',
    ]
    mtimes = [int(path.stat().st_mtime_ns) for path in candidates if path.exists()]
    return max(mtimes) if mtimes else 0


def _session_last_message_ts(session_dir: Path) -> int:
    history_path = session_dir / 'memory' / 'history.jsonl'
    if not history_path.exists():
        return 0
    try:
        with history_path.open('rb') as f:
            f.seek(0, 2)
            end = f.tell()
            if end <= 0:
                return 0
            buffer = b''
            step = 4096
            pos = end
            while pos > 0:
                read_size = step if pos >= step else pos
                pos -= read_size
                f.seek(pos)
                buffer = f.read(read_size) + buffer
                lines = buffer.splitlines()
                while lines:
                    raw = lines.pop()
                    if not raw.strip():
                        continue
                    try:
                        item = json.loads(raw.decode('utf-8'))
                    except Exception:
                        continue
                    try:
                        return int(item.get('ts', 0) or 0)
                    except (TypeError, ValueError):
                        return 0
            return 0
    except Exception:
        return 0


def start_new_game(session_id: str) -> dict:
    session_id = normalize_session_id(session_id)
    _enforce_session_quota()
    new_session_id = _new_session_id(session_id)
    ensure_session_dirs(new_session_id)

    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    root_canon = read_text(resolve_source(sources['canon']))

    save_canon(new_session_id, root_canon if root_canon.strip() else '# Canon\n\n## 世界长期事实\n- 待确认\n')
    state = initialize_opening_state(new_session_id)
    state['continuity_hints'] = []
    state['important_npcs'] = []
    state['active_threads'] = []
    save_state(new_session_id, state)
    save_context(new_session_id, {
        **current_session_owner_context(new_session_id),
        'runtime_rules_path': sources.get('runtime_rules'),
        'character_core_path': sources.get('character_core'),
        'lorebook_path': sources.get('lorebook'),
        'active_preset': sources.get('active_preset'),
        'new_game_initialized': True,
    })
    save_meta(new_session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})

    reply = build_opening_reply('开始游戏')
    ts = int(time.time() * 1000)
    append_history(new_session_id, {'ts': ts, 'role': 'assistant', 'content': reply})

    return {
        'session_id': new_session_id,
        'previous_session_id': session_id,
        'reply': reply,
        'state_snapshot': build_state_snapshot(state),
        'messages': [
            {'ts': ts, 'role': 'assistant', 'content': reply}
        ],
    }


def delete_session(session_id: str) -> dict:
    session_id = normalize_session_id(session_id)
    paths = session_paths(session_id)
    session_dir = paths['session_dir']
    deleted_paths: list[str] = []
    if session_dir.exists():
        shutil.rmtree(session_dir)
        deleted_paths.append(str(session_dir.relative_to(ROOT)))
    return {
        'session_id': session_id,
        'deleted': bool(deleted_paths),
        'deleted_paths': deleted_paths,
        'sessions': list_sessions(),
    }


def list_sessions() -> list[dict]:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    active_character_path = sources.get('character_core')

    items: list[dict] = []
    for session_dir in sorted(iter_session_dirs(), key=lambda p: p.name):
        path = session_dir / 'context.json'
        if not path.exists():
            continue
        session_id = session_dir.name
        if session_id.startswith('archive-'):
            continue
        try:
            context = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            context = {}
        character_path = context.get('character_core_path')
        replay_bootstrap = context.get('replay_bootstrap')
        if character_path and active_character_path and character_path != active_character_path:
            continue
        items.append({
            'session_id': session_id,
            'replay': bool(replay_bootstrap),
            'active_preset': context.get('active_preset'),
            'bootstrapped_main_event': context.get('bootstrapped_main_event'),
            'last_message_ts': _session_last_message_ts(session_dir),
            'updated_at_ns': _session_updated_at(session_dir),
        })
    items.sort(key=lambda item: (item['replay'], -(item.get('last_message_ts') or 0), -item['updated_at_ns'], item['session_id']))
    return items
