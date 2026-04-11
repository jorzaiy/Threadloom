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
    from .paths import iter_session_dirs, resolve_session_dir, session_archive_target
    from .runtime_store import append_history, build_state_snapshot, ensure_session_dirs, save_canon, save_context, save_meta, save_state, save_summary, session_paths
except ImportError:
    from bootstrap_session import load_runtime_config, resolve_source, read_json, read_text
    from opening import build_opening_reply, initialize_opening_state
    from paths import iter_session_dirs, resolve_session_dir, session_archive_target
    from runtime_store import append_history, build_state_snapshot, ensure_session_dirs, save_canon, save_context, save_meta, save_state, save_summary, session_paths


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(__file__).resolve().parents[1]


def _archive_target(session_id: str) -> Path:
    session_dir = resolve_session_dir(session_id)
    return session_archive_target(session_dir, session_id)


def _canonical_base_session_id(session_id: str) -> str:
    text = (session_id or '').strip() or 'story'
    m = re.match(r'^archive-\d{8}-\d{6}-(.+)$', text)
    if m:
        text = m.group(1)
    m = re.match(r'^(.+)-\d{8}-\d{6}$', text)
    if m:
        text = m.group(1)
    return text or 'story'


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


def _session_has_persisted_content(session_dir: Path) -> bool:
    if not session_dir.exists():
        return False
    for path in session_dir.rglob('*'):
        if path.is_file():
            return True
    return False


def archive_session(session_id: str) -> str | None:
    session_dir = resolve_session_dir(session_id, create=False)
    if not session_dir.exists():
        return None
    if not _session_has_persisted_content(session_dir):
        return None
    target = _archive_target(session_id)
    shutil.move(str(session_dir), str(target))
    return str(target.relative_to(ROOT))


def _resolve_relative_session_dir(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    abs_path = path if path.is_absolute() else (ROOT / path)
    return abs_path if abs_path.exists() else None


def _load_context_file(session_dir: Path) -> dict:
    path = session_dir / 'context.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _collect_session_lineage(session_dir: Path) -> list[Path]:
    to_delete: list[Path] = []
    seen: set[Path] = set()
    current = session_dir
    while current and current.exists() and current not in seen:
        seen.add(current)
        to_delete.append(current)
        context = _load_context_file(current)
        next_dir = _resolve_relative_session_dir(context.get('archived_previous_session_to'))
        current = next_dir
    return to_delete


def _all_session_dirs() -> list[Path]:
    return iter_session_dirs()


def _lineage_neighbors() -> dict[Path, set[Path]]:
    mapping: dict[Path, set[Path]] = {}
    for session_dir in _all_session_dirs():
        mapping.setdefault(session_dir, set())
        context = _load_context_file(session_dir)
        linked = _resolve_relative_session_dir(context.get('archived_previous_session_to'))
        if linked and linked.exists():
            mapping.setdefault(linked, set())
            mapping[session_dir].add(linked)
            mapping[linked].add(session_dir)
    return mapping


def _collect_connected_lineage(session_dir: Path) -> list[Path]:
    neighbors = _lineage_neighbors()
    stack = [session_dir]
    seen: set[Path] = set()
    out: list[Path] = []
    while stack:
        current = stack.pop()
        if current in seen or not current.exists():
            continue
        seen.add(current)
        out.append(current)
        for item in neighbors.get(current, set()):
            if item not in seen:
                stack.append(item)
    return out


def start_new_game(session_id: str) -> dict:
    archived_to = archive_session(session_id)
    new_session_id = _new_session_id(session_id)
    ensure_session_dirs(new_session_id)

    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    root_canon = read_text(resolve_source(sources['canon']))

    save_canon(new_session_id, root_canon if root_canon.strip() else '# Canon\n\n## 世界长期事实\n- 待确认\n')
    save_summary(new_session_id, '# Summary\n\n## 当前状态锚点\n- 暂无\n\n## 活跃线程\n- 暂无\n\n## 当前裁定信号\n- 暂无\n\n## 最近变化\n- 暂无\n\n## 未决问题\n- 暂无\n')
    state = initialize_opening_state(new_session_id)
    state['continuity_hints'] = []
    state['important_npcs'] = []
    state['active_threads'] = []
    save_state(new_session_id, state)
    save_context(new_session_id, {
        'runtime_rules_path': sources.get('runtime_rules'),
        'character_core_path': sources.get('character_core'),
        'lorebook_path': sources.get('lorebook'),
        'active_preset': sources.get('active_preset'),
        'new_game_initialized': True,
        'archived_previous_session_to': archived_to,
    })
    save_meta(new_session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})

    reply = build_opening_reply('开始游戏')
    ts = int(time.time() * 1000)
    append_history(new_session_id, {'ts': ts, 'role': 'assistant', 'content': reply})

    return {
        'session_id': new_session_id,
        'previous_session_id': session_id,
        'archived_to': archived_to,
        'reply': reply,
        'state_snapshot': build_state_snapshot(state),
        'messages': [
            {'ts': ts, 'role': 'assistant', 'content': reply}
        ],
    }


def delete_session(session_id: str) -> dict:
    paths = session_paths(session_id)
    session_dir = paths['session_dir']
    deleted_paths: list[str] = []
    if session_dir.exists():
        lineage = _collect_connected_lineage(session_dir)
        lineage.sort(key=lambda p: p.name)
        for path in lineage:
            if path.exists():
                shutil.rmtree(path)
                deleted_paths.append(str(path.relative_to(ROOT)))
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
            'archived': session_id.startswith('archive-'),
            'replay': bool(replay_bootstrap),
            'active_preset': context.get('active_preset'),
            'bootstrapped_main_event': context.get('bootstrapped_main_event'),
            'updated_at_ns': _session_updated_at(session_dir),
        })
    items.sort(key=lambda item: (item['archived'], item['replay'], -item['updated_at_ns'], item['session_id']))
    return items
